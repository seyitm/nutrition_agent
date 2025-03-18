from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig, LLMConfig
from crawl4ai.extraction_strategy import LLMExtractionStrategy
from pydantic import BaseModel, Field
from googlesearch import search
import os
from dotenv import load_dotenv
import uvicorn
from typing import Optional, List, Dict


load_dotenv()

api_token = os.getenv("GOOGLE_API_KEY")
if not api_token:
    raise ValueError("GOOGLE_API_KEY .env dosyasından çekilemedi! Lütfen .env dosyasını kontrol edin.")

app = FastAPI(
    title="Nutrition API",
    description="Yiyeceklerin besin değerlerini web'den otomatik olarak çeken hafif bir API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class NutritionData(BaseModel):
    calories: str = Field(..., description="Kalori değeri")
    protein: str = Field(..., description="Protein miktarı")
    sugar: str = Field(..., description="Şeker miktarı")
    carbohydrates: str = Field(..., description="Karbonhidrat miktarı")
    fat: str = Field(..., description="Yağ miktarı")
    serving_size: str = Field(..., description="Porsiyon büyüklüğü")
    allergens: Optional[List[str]] = Field(default=None, description="Alerjenler")
    vitamin_minerals: Optional[Dict[str, str]] = Field(default=None, description="Vitamin ve mineraller")


async def crawl_nutrition(food_name: str, language: str = "tr"):
    try:
        keywords_by_lang = {
            "tr": ["besin değeri", "besin bilgisi", "besin içeriği", "karbonhidrat", "protein", "yağ", "kalori", "şeker"],
            "en": ["nutrition facts", "nutritional information", "carbohydrates", "protein", "fat", "calories", "sugar"]
        }
        
        search_query_templates = {
            "tr": "{food_name} besin değeri",
            "en": "{food_name} nutrition facts"
        }
        
    
        instructions_by_lang = {
    "tr": """Web sayfasındaki besin değerlerini analiz et ve tek bir JSON objesi olarak döndür.
    Yanıt, verilen şemaya (calories, protein, sugar, carbohydrates, fat, serving_size, allergens, vitamin_minerals) tam olarak uymalı.
    Eğer bir veri eksikse, o alanı 'Bilinmiyor' olarak doldur.
    Sayfada birden fazla besin bilgisi varsa, en belirgin olanı (örneğin, 100g veya ana ürün) seç.
    Metrik birimler (kcal, g, mg) kullan, bir boşlukla ayır (örneğin, '47 kcal').
    Alerjen yoksa boş liste ([]) döndür, vitamin-mineral içeriğini ekle.""",
    
    "en": """Analyze the nutrition facts on the webpage and return them as a single JSON object.
    The response must exactly match the given schema (calories, protein, sugar, carbohydrates, fat, serving_size, allergens, vitamin_minerals).
    If any data is missing, fill that field with 'Unknown'.
    If there are multiple nutrition facts on the page, choose the most prominent one (e.g., 100g or main product).
    Use metric units (kcal, g, mg) with a space (e.g., '47 kcal').
    Return an empty list ([]) for allergens if none, and include vitamin-mineral content if available."""
}
        
        
        selected_lang = language if language in keywords_by_lang else "tr"
        search_query = search_query_templates[selected_lang].format(food_name=food_name)
        instruction = instructions_by_lang[selected_lang]
        
        
        llm_strategy = LLMExtractionStrategy(
            llm_config=LLMConfig(provider="gemini/gemini-1.5-pro", api_token=api_token),
            schema=NutritionData.model_json_schema(),
            extraction_type="schema",
            instruction=instruction
        )
        

        browser_config = BrowserConfig(
            browser_type="chromium",
            headless=True,
            verbose=False,  
        )

        
        run_config = CrawlerRunConfig(
            extraction_strategy=llm_strategy,
            excluded_tags=['form', 'header', 'footer', 'nav', 'aside'],
            magic=True,
            exclude_social_media_links=True,
            exclude_external_images=True,
            word_count_threshold=10,
        )
        
        urls = list(search(search_query, num_results=2, unique=True))
        async with AsyncWebCrawler(config=browser_config) as crawler:
            results = await crawler.arun(url=urls[0], config=run_config)
            import json
            extracted = json.loads(results.extracted_content)
            if isinstance(extracted, list): 
                extracted = extracted[0]
            extracted["source_url"] = results.url
            return extracted
    
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hata: {str(e)}")

@app.get("/nutrition/{food_name}")
async def get_nutrition(
    food_name: str,
    language: str = Query("tr", description="Arama dili (tr veya en)"),
):
    try:
        return await crawl_nutrition(food_name, language)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Beklenmeyen hata: {str(e)}")
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)