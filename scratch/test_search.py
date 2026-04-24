from duckduckgo_search import DDGS

def test_search():
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text("hello", max_results=1))
            print(f"Results found: {len(results)}")
            if results:
                print(results[0])
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_search()
