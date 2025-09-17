#!/usr/bin/env python3
"""
BMW CarData Catalogue Library

A library for fetching and caching BMW's official CarData catalogue using their API.
Provides local caching with refresh capability and convenient lookup functions.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests


logger = logging.getLogger(__name__)


class BMWCatalogueClient:
    """Client for BMW CarData catalogue API with local caching."""

    def __init__(self, cache_file: str = "bmw_data_catalogue.json"):
        """
        Initialize catalogue client.
        
        Args:
            cache_file: Path to local cache file
        """
        self.cache_file = Path(cache_file)
        self.base_url = "https://www.bmw.co.uk/en-gb/utilities/bmw/api/cd/catalogue"
        self.catalogue_data = {}
        self.categories_info = {}
        
        # Load cache or refresh if no valid cache exists
        if not self._load_cache():
            logger.info("No valid cache found, fetching from API...")
            self.refresh_cache()

    def _load_cache(self) -> bool:
        """Load catalogue data from cache file if available."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Expect new API format with metadata and items
                    if isinstance(data, dict) and "items" in data and "metadata" in data:
                        # items is now already a dictionary indexed by ID
                        if isinstance(data["items"], dict):
                            self.catalogue_data = data["items"]
                        else:
                            # Handle old format where items was an array
                            self.catalogue_data = {item["id"]: item for item in data["items"]}
                        self.categories_info = data.get("categories", {})
                        logger.info(f"Loaded {len(self.catalogue_data)} items from cache")
                        return True
                    else:
                        logger.warning("Cache file is in old format, will refresh from API")
                        return False
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load cache from {self.cache_file}: {e}")
        return False

    def _save_cache(self, full_data: Dict[str, Any]):
        """Save catalogue data to cache file."""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(full_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved catalogue data to {self.cache_file}")
        except IOError as e:
            logger.error(f"Could not save cache to {self.cache_file}: {e}")

    def _fetch_page(self, offset: int = 0, category: str = "") -> Optional[Dict[str, Any]]:
        """
        Fetch a single page from the catalogue API.
        
        Args:
            offset: Starting offset for pagination
            category: Optional category filter
            
        Returns:
            API response data or None if error
        """
        params = {
            "streamable": "true",
            "offset": str(offset),
            "q": "",
            "category": category
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            logger.debug(f"API response: {data}")
            
            # Check success field - it might be "status": "SUCCESS" instead
            if data.get("success") or data.get("status") == "SUCCESS":
                return data
            else:
                logger.error(f"API returned error: {data}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"Error fetching catalogue page at offset {offset}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON response: {e}")
            return None

    def fetch_all_items(self, category: str = "") -> Dict[str, Any]:
        """
        Fetch all catalogue items using pagination.
        
        Args:
            category: Optional category filter
            
        Returns:
            Complete catalogue data with metadata
        """
        logger.info("Fetching BMW CarData catalogue from API...")
        
        all_items = []
        offset = 0
        page_size = 10  # API default
        
        while True:
            logger.info(f"Fetching page at offset {offset}...")
            page_data = self._fetch_page(offset, category)
            
            if not page_data:
                logger.error(f"Failed to fetch page at offset {offset}")
                break
                
            # Items are nested under 'data'
            data_section = page_data.get("data", {})
            items = data_section.get("items", [])
            logger.info(f"Got {len(items)} items on this page")
            all_items.extend(items)
            
            # Debug: show some info about the response
            logger.debug(f"Page data keys: {list(page_data.keys())}")
            logger.debug(f"Total items so far: {len(all_items)}")
            
            # Check if we have more pages - hasNextPage is also under 'data'
            if not data_section.get("hasNextPage", False):
                logger.info(f"Reached last page. Total items: {len(all_items)}")
                break
                
            offset += page_size
            
            # Small delay to be respectful to the API
            time.sleep(0.1)

        # Create indexed dictionary for fast lookups
        indexed_items = {item["id"]: item for item in all_items}
        
        # Extract category information from the last page response
        categories_info = {}
        if page_data and page_data.get("data", {}).get("categories"):
            categories_info = page_data["data"]["categories"]
        
        # Create complete data structure with metadata
        complete_data = {
            "metadata": {
                "fetched_at": time.time(),
                "total_items": len(all_items),
                "api_url": self.base_url,
                "category_filter": category
            },
            "categories": categories_info,
            "items": indexed_items
        }
        
        logger.info(f"Successfully fetched {len(all_items)} catalogue items")
        return complete_data

    def refresh_cache(self, category: str = "") -> bool:
        """
        Force refresh of local cache from API.
        
        Args:
            category: Optional category filter
            
        Returns:
            True if successful, False otherwise
        """
        logger.info("Refreshing catalogue cache...")
        
        data = self.fetch_all_items(category)
        if not data or not data.get("items") or len(data.get("items", {})) == 0:
            logger.error("Failed to fetch catalogue data or got empty results")
            return False
            
        self._save_cache(data)
        self.catalogue_data = data["items"]
        self.categories_info = data.get("categories", {})
        return True

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific catalogue item by ID.
        
        Args:
            item_id: Technical ID of the data point
            
        Returns:
            Item data or None if not found
        """
        return self.catalogue_data.get(item_id)

    def get_display_name(self, item_id: str) -> str:
        """
        Get human-readable display name for an item.
        
        Args:
            item_id: Technical ID of the data point
            
        Returns:
            Display name or the original ID if not found
        """
        item = self.get_item(item_id)
        return item.get("name", item_id) if item else item_id

    def get_unit(self, item_id: str) -> Optional[str]:
        """
        Get unit for an item.
        
        Args:
            item_id: Technical ID of the data point
            
        Returns:
            Unit string or None if not found/available
        """
        item = self.get_item(item_id)
        if item and item.get("unit"):
            unit = item["unit"].strip()
            return unit if unit and unit != "-" else None
        return None

    def get_description(self, item_id: str) -> Optional[str]:
        """
        Get description for an item.
        
        Args:
            item_id: Technical ID of the data point
            
        Returns:
            Description string or None if not found
        """
        item = self.get_item(item_id)
        return item.get("description") if item else None

    def get_datatype(self, item_id: str) -> Optional[str]:
        """
        Get data type for an item.
        
        Args:
            item_id: Technical ID of the data point
            
        Returns:
            Data type string or None if not found
        """
        item = self.get_item(item_id)
        return item.get("datatype") if item else None

    def get_category(self, item_id: str) -> Optional[str]:
        """
        Get category for an item.
        
        Args:
            item_id: Technical ID of the data point
            
        Returns:
            Category string or None if not found
        """
        item = self.get_item(item_id)
        return item.get("category") if item else None

    def get_range(self, item_id: str) -> Optional[str]:
        """
        Get value range for an item.
        
        Args:
            item_id: Technical ID of the data point
            
        Returns:
            Range string or None if not found
        """
        item = self.get_item(item_id)
        return item.get("range") if item else None

    def search_items(self, query: str) -> List[Dict[str, Any]]:
        """
        Search catalogue items by name or ID.
        
        Args:
            query: Search query (case-insensitive)
            
        Returns:
            List of matching items
        """
        query_lower = query.lower()
        matches = []
        
        for item in self.catalogue_data.values():
            if (query_lower in item.get("name", "").lower() or 
                query_lower in item.get("id", "").lower() or
                query_lower in item.get("description", "").lower()):
                matches.append(item)
                
        return matches

    def get_categories(self) -> List[str]:
        """Get list of all categories in the catalogue."""
        if self.categories_info:
            # Use cached category info, sorted by rank
            return sorted(self.categories_info.keys(), 
                         key=lambda cat: self.categories_info[cat].get("rank", 999))
        else:
            # Fallback to extracting from items
            categories = set()
            for item in self.catalogue_data.values():
                if "category" in item:
                    categories.add(item["category"])
            return sorted(list(categories))

    def get_category_info(self, category: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a category.
        
        Args:
            category: Category name
            
        Returns:
            Category info with description and rank, or None if not found
        """
        return self.categories_info.get(category)

    def get_category_description(self, category: str) -> Optional[str]:
        """
        Get description for a category.
        
        Args:
            category: Category name
            
        Returns:
            Category description or None if not found
        """
        info = self.get_category_info(category)
        return info.get("description") if info else None

    def get_category_rank(self, category: str) -> Optional[int]:
        """
        Get rank for a category.
        
        Args:
            category: Category name
            
        Returns:
            Category rank or None if not found
        """
        info = self.get_category_info(category)
        return info.get("rank") if info else None

    def get_items_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        Get all items in a specific category.
        
        Args:
            category: Category name
            
        Returns:
            List of items in the category
        """
        return [item for item in self.catalogue_data.values() 
                if item.get("category") == category]

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the cached catalogue."""
        if not self.catalogue_data:
            return {"total_items": 0}
            
        categories = {}
        datatypes = {}
        
        for item in self.catalogue_data.values():
            # Count by category
            category = item.get("category", "Unknown")
            categories[category] = categories.get(category, 0) + 1
            
            # Count by datatype
            datatype = item.get("datatype") or "Unknown"
            datatypes[datatype] = datatypes.get(datatype, 0) + 1
        
        return {
            "total_items": len(self.catalogue_data),
            "categories": categories,
            "datatypes": datatypes,
            "cache_file": str(self.cache_file),
            "cache_exists": self.cache_file.exists()
        }


def main():
    """Command-line interface for catalogue operations."""
    import argparse
    
    parser = argparse.ArgumentParser(description="BMW CarData Catalogue Manager")
    parser.add_argument("--refresh", action="store_true", 
                       help="Force refresh of catalogue cache")
    parser.add_argument("--stats", action="store_true",
                       help="Show catalogue statistics")
    parser.add_argument("--search", type=str,
                       help="Search catalogue items")
    parser.add_argument("--category", type=str,
                       help="Filter by category")
    parser.add_argument("--list-categories", action="store_true",
                       help="List all categories with descriptions")
    parser.add_argument("--cache-file", type=str, default="bmw_data_catalogue.json",
                       help="Cache file path")
    
    args = parser.parse_args()
    
    # Set up logging
    logging.basicConfig(level=logging.INFO, 
                       format='%(asctime)s - %(levelname)s - %(message)s')
    
    client = BMWCatalogueClient(args.cache_file)
    
    if args.refresh:
        print("Refreshing catalogue cache...")
        if client.refresh_cache(args.category or ""):
            print("Cache refreshed successfully!")
        else:
            print("Failed to refresh cache")
            return 1
    
    if args.stats:
        stats = client.get_stats()
        print("\nCatalogue Statistics:")
        print(f"  Total items: {stats['total_items']}")
        print(f"  Cache file: {stats['cache_file']}")
        print(f"  Cache exists: {stats['cache_exists']}")
        
        if stats.get('categories'):
            print("\n  Categories:")
            for cat, count in sorted(stats['categories'].items()):
                desc = client.get_category_description(cat)
                rank = client.get_category_rank(cat)
                if desc and rank:
                    print(f"    {cat}: {count} items (rank {rank}) - {desc}")
                else:
                    print(f"    {cat}: {count} items")
                
        if stats.get('datatypes'):
            print("\n  Data types:")
            for dtype, count in sorted(stats['datatypes'].items()):
                print(f"    {dtype}: {count} items")
    
    if args.search:
        results = client.search_items(args.search)
        print(f"\nSearch results for '{args.search}': {len(results)} items")
        for item in results[:10]:  # Show first 10 results
            unit = f" ({item['unit']})" if item.get('unit') else ""
            print(f"  {item['name']}{unit}")
            print(f"    ID: {item['id']}")
            if item.get('description'):
                print(f"    Description: {item['description'][:100]}...")
            print()
    
    if args.list_categories:
        categories = client.get_categories()
        print(f"\nAll Categories ({len(categories)}):")
        for cat in categories:
            desc = client.get_category_description(cat)
            rank = client.get_category_rank(cat)
            items_count = len(client.get_items_by_category(cat))
            if desc and rank:
                print(f"  {rank}. {cat}: {items_count} items")
                print(f"     {desc}")
            else:
                print(f"  {cat}: {items_count} items")
            print()
    
    if args.category:
        items = client.get_items_by_category(args.category)
        desc = client.get_category_description(args.category)
        print(f"\nItems in category '{args.category}': {len(items)}")
        if desc:
            print(f"Description: {desc}")
        print()
        for item in items[:20]:  # Show first 20 items
            unit = f" ({item['unit']})" if item.get('unit') else ""
            print(f"  {item['name']}{unit}")
            print(f"    ID: {item['id']}")
    
    return 0


if __name__ == "__main__":
    exit(main())