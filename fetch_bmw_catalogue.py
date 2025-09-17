#!/usr/bin/env python3
"""
BMW CarData Catalogue Fetcher

Downloads the BMW Customer Telematics Data Catalogue HTML and parses it into a structured JSON file.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List

import requests
from bs4 import BeautifulSoup


def clean_text(text: str) -> str:
    """Remove invisible characters and normalize whitespace."""
    if not text:
        return text

    # Replace non-breaking spaces and other space-like chars with regular spaces
    space_chars = [
        "\u00a0",  # Non-breaking space
        "\u2009",  # Thin space
        "\u202f",  # Narrow no-break space
    ]

    for char in space_chars:
        text = text.replace(char, " ")

    # Remove truly invisible characters (zero-width)
    invisible_chars = [
        "\u200b",  # Zero-width space
        "\u200c",  # Zero-width non-joiner
        "\u200d",  # Zero-width joiner
        "\u2060",  # Word joiner
        "\ufeff",  # Zero-width no-break space
    ]

    for char in invisible_chars:
        text = text.replace(char, "")

    # Normalize multiple spaces to single spaces, but keep all words
    text = " ".join(text.split())

    return text


def download_catalogue(url: str) -> str:
    """Download the HTML catalogue from BMW's API."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error downloading catalogue: {e}")
        sys.exit(1)


def parse_table_data(table) -> List[Dict]:
    """Parse a table into structured data."""
    rows = table.find_all("tr")
    if not rows:
        return []

    # Find header row
    header_row = None
    for row in rows:
        if row.find("th"):
            header_row = row
            break

    if not header_row:
        return []

    # Extract headers
    headers = []
    for th in header_row.find_all("th"):
        text = clean_text(th.get_text(strip=True))
        headers.append(text)

    # Extract data rows
    data_rows = []
    for row in rows:
        if row == header_row or not row.find("td"):
            continue

        cells = row.find_all("td")
        if len(cells) != len(headers):
            continue

        row_data = {}
        for i, cell in enumerate(cells):
            if i < len(headers):
                # Handle streamable column (check for div classes)
                if "Streamable" in headers[i]:
                    streamable_div = cell.find("div")
                    if streamable_div:
                        if "true-tick" in streamable_div.get("class", []):
                            value = True
                        elif "false-tick" in streamable_div.get("class", []):
                            value = False
                        else:
                            value = None
                    else:
                        value = None
                else:
                    value = cell.get_text(strip=True)
                    # Clean up all invisible characters
                    value = clean_text(value)

                row_data[headers[i]] = value

        if row_data:
            data_rows.append(row_data)

    return data_rows


def to_snake_case(text: str) -> str:
    """Convert text to snake_case."""
    # Remove special characters and replace spaces with underscores
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text.lower()


def parse_catalogue_html(html_content: str) -> Dict:
    """Parse the HTML catalogue into structured data."""
    soup = BeautifulSoup(html_content, "html.parser")

    # Collect all data elements across all categories
    data_elements = {}
    h3_elements = soup.find_all("h3")

    for h3 in h3_elements:
        # Find the next table after this h3
        table = h3.find_next_sibling("table")
        if table:
            table_data = parse_table_data(table)

            for item in table_data:
                technical_descriptor = item.get("Technical descriptor", "").strip()
                if not technical_descriptor:
                    continue

                # Convert header names to snake_case
                element_data = {}
                for key, value in item.items():
                    if key != "Technical descriptor":  # Skip the key we're using
                        snake_key = to_snake_case(key)
                        element_data[snake_key] = value

                data_elements[technical_descriptor] = element_data

    return data_elements


def main():
    """Main function."""
    url = "https://mybmwweb-utilities.api.bmw/en-gb/utilities/bmw/api/cd/catalogue/file"
    output_file = Path("bmw_data_catalogue.json")

    print("Downloading BMW CarData catalogue...")
    html_content = download_catalogue(url)

    print("Parsing catalogue data...")
    catalogue_data = parse_catalogue_html(html_content)

    print(f"Found {len(catalogue_data)} data elements")

    # Write JSON output
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(catalogue_data, f, indent=2, ensure_ascii=False)

    print(f"Catalogue data saved to {output_file}")

    # Print summary
    streamable_count = sum(
        1 for data in catalogue_data.values() if data.get("streamable") is True
    )
    print(f"Total streamable elements: {streamable_count}")

    # Show a few examples
    print("\nExample elements:")
    for i, (key, data) in enumerate(catalogue_data.items()):
        if i >= 3:  # Show first 3
            break
        print(f"  {key}: {data.get('cardata_element', 'N/A')}")
        if data.get("streamable"):
            print("    -> Streamable: ✓")


if __name__ == "__main__":
    main()
