import asyncio
import os
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Get current path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)  # Get parent directory (project root)
app_dir = os.path.join(parent_dir, 'app')  # Path to app directory
print(f"Current directory: {current_dir}")
print(f"App directory: {app_dir}")

# Add app directory to path
sys.path.insert(0, parent_dir)

# Check config.json existence
config_path = os.path.join(app_dir, 'fetchers', 'Config', 'config.json')
print(f"Config.json path: {config_path}")
print(f"File exists: {os.path.exists(config_path)}")

# Import RSS fetcher
try:
    from app.fetchers.rss import RSSFetcher

    print("RSS fetcher successfully imported")
except Exception as e:
    print(f"Error importing RSS fetcher: {e}")
    import traceback

    traceback.print_exc()


# Test function for fetcher
async def test_fetcher():
    try:
        # Create test fetcher
        fetcher = RSSFetcher('test_bens', 'https://bensbites.beehiiv.com/feeds/latest.rss', 'en')
        print("Fetcher created, starting request...")

        # Get news
        news = await fetcher.fetch()
        print(f"Received news items: {len(news)}")

        # Print first news item
        if news:
            print(f"First news title: {news[0].get('title')}")

        return True
    except Exception as e:
        print(f"Error running fetcher: {e}")
        import traceback
        traceback.print_exc()
        return False


# Function to test scheduler
async def test_scheduler():
    try:
        # Check scheduler import
        from app.scheduler import load_config, init_scheduler
        print("Scheduler successfully imported")

        # Load configuration
        config = load_config()
        print(f"Loaded {len(config)} sources from configuration")

        # Initialize scheduler
        print("Starting scheduler initialization...")
        await init_scheduler()
        print("Scheduler successfully initialized")

        # Wait 10 seconds
        print("Waiting 10 seconds...")
        await asyncio.sleep(10)

        return True
    except Exception as e:
        print(f"Error testing scheduler: {e}")
        import traceback
        traceback.print_exc()
        return False


# Main function
async def main():
    print("=== FETCHER TESTING ===")
    fetcher_success = await test_fetcher()

    if fetcher_success:
        print("\n=== SCHEDULER TESTING ===")
        await test_scheduler()
    else:
        print("Scheduler testing skipped due to fetcher errors")


if __name__ == "__main__":
    asyncio.run(main())