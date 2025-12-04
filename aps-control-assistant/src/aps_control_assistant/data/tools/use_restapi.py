"""
EPICS Archiver Appliance REST API Data Retrieval Example

This script demonstrates how to retrieve archived data from an EPICS Archiver Appliance
using its REST API. It shows how to:
- Generate multiple PV names using templates and ranges
- Retrieve data in various formats (JSON, CSV, MAT, etc.)
- Handle time range queries with timezone conversion
- Process bulk PV data retrieval with error handling
"""

import requests
from itertools import product
from datetime import datetime
import zoneinfo

# Create a session for HTTP requests
session = requests.Session()
session.trust_env = False
session.verify = False

def get_data_with_format(pv, start, stop, data_url, data_type='json', debug=False):
    """
    Fetch data from the Archiver Appliance in the specified format.

    Parameters:
        pv (str): The process variable name.
        start (str): ISO 8601 UTC start time (e.g., '2025-03-27T08:00:00Z').
        stop (str): ISO 8601 UTC stop time (e.g., '2025-03-28T08:00:00Z').
        data_url (str): Base URL of the appliance.
        data_type (str): Response format. Options:
                         'json', 'csv', 'mat', 'raw', 'txt', 'svg'.
        debug (bool): If True, prints request URL and status.

    Returns:
        - dict for 'json'
        - str for 'csv', 'txt', 'svg'
        - bytes for 'mat', 'raw'
    """
    if data_url is None:
        raise ValueError("dataURL parameter is required")
    
    url = f"{data_url}/data/getData.{data_type}"

    params = {
        'pv': pv,
        'from': start,
        'to': stop
    }

    resp = session.get(url, params=params, timeout=(0.5, 10))

    if debug:
        print(f"URL: {resp.url}")
        print(f"Status Code: {resp.status_code}")
        
    resp.raise_for_status()

    if data_type == 'json':
        return resp.json()
    elif data_type in ['csv', 'txt', 'svg']:
        return resp.text
    elif data_type in ['mat', 'raw']:
        return resp.content
    else:
        raise ValueError(f"Unsupported data type: {data_type}")

# Generate PV names using a flexible template and value ranges.
def generate_pv_names(template, ranges):
    """
    Args:
        template (str): Format string with placeholders (e.g. 'S{sector:02}A:P{bpm}:hp_temp:ts{sensor}').
                        Use format codes like {:02} to add leading zeros (e.g. 1 → '01').

        ranges (dict): Keys match placeholders in the template.
                       Values are iterables like range() or lists.

    Returns:
        list[str]: List of generated PV names.
    """
    
    keys = ranges.keys()
    values = ranges.values()

    pv_names = []
    for combo in product(*values):
        pv_names.append(template.format(**dict(zip(keys, combo))))

    return pv_names

def get_data(pv_names, start, stop, file_format, data_url):
    """
    Retrieve archival data for a list of PVs over a specified time range.

    Args:
        pv_names (list): List of PV names to query.
        start (datetime): Start timestamp as datetime object.
        stop (datetime): Stop timestamp as datetime object.
        file_format (str): Data format ('json', 'csv', etc.).
        data_url (str): Base URL of the archiver appliance.
    """
    iso_start = convert_time_to_iso8601_utc(start)
    iso_stop = convert_time_to_iso8601_utc(stop)
    
    all_data = []
    for pv_name in pv_names:
        try:
            response = get_data_with_format(pv_name, iso_start, iso_stop, data_url, file_format)
            print(f"[OK] Retrieved data for PV: {pv_name}")
            if isinstance(response, list):
                all_data.extend(response)
            else:
                all_data.append(response)
        except Exception as e:
            print(f"[ERROR] Failed to retrieve data for PV '{pv_name}': {e}")
    return all_data

def convert_time_to_iso8601_utc(time: datetime) -> str:
    """Ensure datetime is timezone-aware (default to Chicago), then convert to UTC ISO 8601 string."""
    
    chicago = zoneinfo.ZoneInfo("America/Chicago")

    # If the input datetime is naive, assume it's in Chicago time
    if time.tzinfo is None:
        time = time.replace(tzinfo=chicago)

    # Convert to UTC
    time_utc = time.astimezone(zoneinfo.ZoneInfo("UTC"))
    
    # Format as ISO 8601 with Z
    iso_time = time_utc.isoformat().replace('+00:00', 'Z')

    return iso_time

if __name__ == "__main__":
    
    # Set URLs for AA
    data_url = 'http://pvarchiver.aps.anl.gov:17668/retrieval'
        
    # Generate PV names
    template = "S{sector:02}A:P{bpm}:hp_temp:ts{sensor}"
    ranges = {
        "sector": range(2, 3),   # → 01, 02, ..., 40 via {sector:02}
        "bpm": range(1, 2),       # → 0, 1, ..., 6
        "sensor": range(1, 2)     # → 1, 2, ..., 8
    }
    # pv_names = generate_pv_names(template, ranges)
    pv_names = ["S-DCCT:CurrentM"]
 
    # Set time range
    # datetime format: datetime(year, month, day, hour, minute, second)
    # Example: datetime(2025, 3, 27, 8, 0, 0)
    start = datetime(2025, 11, 24, 12, 0, 0)
    stop = datetime(2025, 11, 24, 14, 0, 0)
    
    # Get data
    # The EPICS Archiver Appliance supports data retrieval in multiple formats/MIME types: JSON, CSV, MAT, RAW, TXT, SVG.
    data = get_data(pv_names, start, stop, "json", data_url)
    print(data)
