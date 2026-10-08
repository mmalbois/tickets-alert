import asyncio

from playwright.async_api import async_playwright


URL = "https://www.ticketone.it/en/artist/galleria-borghese/galleria-borghese-2253937/"


async def main():

    print("==============================")
    print("DIAGNOSTIC TICKETONE")
    print("==============================")

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        page = await browser.new_page()

        def on_request(request):
            url = request.url

            interesting = any(
                word in url.lower()
                for word in [
                    "api",
                    "event",
                    "ticket",
                    "seat",
                    "availability",
                    "calendar",
                    "performance",
                    "product",
                    "eventim",
                    "ticketone",
                ]
            )

            if interesting:
                print()
                print(">>> REQUETE INTERESSANTE")
                print(request.method, url)

        page.on(
            "request",
            on_request
        )

        print()
        print("Ouverture de TicketOne...")

        try:

            await page.goto(
                URL,
                wait_until="commit",
                timeout=30000
            )

            print("TicketOne a commencé à répondre.")

        except Exception as error:

            print(
                f"Navigation interrompue : {error}"
            )

        print()
        print("Attente de 20 secondes pour observer le réseau...")

        await page.wait_for_timeout(20000)

        print()
        print("Diagnostic terminé.")

        await browser.close()


asyncio.run(main())
