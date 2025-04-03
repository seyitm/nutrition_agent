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
from urllib.parse import urlparse # Add this import


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
            llm_config=LLMConfig(provider="gemini/gemini-1.5-flash", api_token=api_token), # Changed model to gemini-1.5-flash
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

        print(f"crawl_nutrition: Searching for {search_query}")
        # Get more results to have options
        urls_raw = list(search(search_query, num_results=5, unique=True))
        print(f"crawl_nutrition: Found raw URLs: {urls_raw}")

        # --- Basic Filtering (remove obvious non-content) ---
        blocked_domains = ["google.com", "gstatic.com", "youtube.com", "pinterest.com", "amazon.com", "facebook.com", "instagram.com", "twitter.com"] # Add more if needed

        filtered_urls = []
        for url in urls_raw:
            try:
                domain = urlparse(url).netloc.lower()
                is_blocked = any(blocked in domain for blocked in blocked_domains)
                # Also check if URL ends with common image extensions (basic check)
                is_image = url.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp'))
                if not is_blocked and not is_image:
                    filtered_urls.append(url)
            except Exception:
                continue # Ignore invalid URLs

        print(f"crawl_nutrition: Filtered URLs: {filtered_urls}")

        if not filtered_urls:
            raise HTTPException(status_code=404, detail="No suitable web pages found from search results.")

        # --- Iterate and Crawl ---
        extracted_data = None # To store the first validated result
        last_successful_crawl_result = None # To store the last result that was successfully crawled/parsed
        async with AsyncWebCrawler(config=browser_config) as crawler:
            for target_url in filtered_urls[:3]: # Try top 3 filtered URLs
                print(f"crawl_nutrition: Trying URL: {target_url}")
                try:
                    print(f"crawl_nutrition: Starting crawler for {target_url}")
                    # Add a timeout to the crawl attempt itself
                    run_config.timeout = 45 # Timeout per URL crawl
                    results = await crawler.arun(url=target_url, config=run_config)
                    print(f"crawl_nutrition: Crawler finished for {target_url}")
                    import json
                    extracted = json.loads(results.extracted_content)
                    if isinstance(extracted, list):
                        extracted = extracted[0] # Take the first item if response is a list

                    # Store this as the latest successful crawl, even if data is "Unknown"
                    if isinstance(extracted, dict) and extracted:
                         extracted["source_url"] = results.url
                         last_successful_crawl_result = extracted
                         print(f"crawl_nutrition: Successfully crawled and parsed {target_url}")
                    else:
                         # Should not happen often if json.loads succeeded, but handle anyway
                         print(f"crawl_nutrition: Parsed JSON from {target_url} was empty or not a dict.")
                         continue # Skip validation if parsing gave weird result

                    # Check if this successful crawl *also* passes validation
                    if any(v is not None and v != "Unknown" for k, v in extracted.items() if k not in ["allergens", "vitamin_minerals", "source_url", "error"]):
                        extracted_data = last_successful_crawl_result # Store the validated data
                        print(f"crawl_nutrition: Found validated data from {target_url}")
                        break # Stop after first validated extraction
                    else:
                        # Data was parsed but didn't pass validation (e.g., all "Unknown")
                        print(f"crawl_nutrition: Data from {target_url} parsed but did not pass validation.")

                except json.JSONDecodeError:
                    print(f"crawl_nutrition: Failed to decode JSON from {target_url}")
                    continue # Try next URL
                except Exception as crawl_error:
                    # Catch specific timeout errors if possible, otherwise general exception
                    print(f"crawl_nutrition: Error crawling or processing {target_url}: {crawl_error}")
                    continue # Try next URL

        # --- Determine final result ---
        if extracted_data:
            # We found a result that passed validation
            print(f"crawl_nutrition: Returning validated data: {extracted_data}")
            return extracted_data
        elif last_successful_crawl_result:
            # No validated result found, but at least one URL was crawled successfully
            print(f"crawl_nutrition: Returning last successful (but unvalidated) crawl result: {last_successful_crawl_result}")
            return last_successful_crawl_result
        else:
            # All crawl attempts failed with errors
            print("crawl_nutrition: All crawl attempts failed.")
            raise HTTPException(status_code=404, detail="Could not extract nutrition data from any source after trying multiple pages.")

    except Exception as e:
        # Catch exceptions from the overall process (like search failing)
        print(f"crawl_nutrition: General Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
