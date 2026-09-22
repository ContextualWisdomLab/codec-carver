from playwright.sync_api import sync_playwright

def test_ui():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto("http://localhost:8000/")

        # Test 1: valid input
        page.locator("#target_bytes").fill("1000")
        page.wait_for_timeout(500)

        print("Valid output:")
        print(page.locator("#target_bytes_preview").inner_text())

        # Test 2: invalid input character "e"
        page.locator("#target_bytes").type("e")
        page.wait_for_timeout(500)

        print("Invalid output:")
        print(page.locator("#target_bytes_preview").inner_text())

        browser.close()

if __name__ == "__main__":
    test_ui()
