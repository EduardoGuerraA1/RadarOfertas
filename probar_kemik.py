import asyncio
import sys
import os

# Asegurar que python encuentre la ruta src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from radar_ofertas.infrastructure.scrapers.kemik_scraper import KemikScraper

async def main():
    print("Iniciando prueba táctica del Scraper de Kemik...")
    scraper = KemikScraper()
    
    query = "teclado"  # Puedes cambiar la búsqueda de prueba aquí
    print(f"Buscando productos para el término: '{query}' en Kemik...\n")
    
    ofertas = await scraper.buscar_producto(query)
    
    if not ofertas:
        print("⚠️ No se encontraron ofertas o los selectores CSS necesitan un ajuste fino.")
    else:
        print(f"¡Éxito! Se extrajeron {len(ofertas)} ofertas:\n")
        for i, oferta in enumerate(ofertas[:5], 1):  # Muestra los primeros 5 resultados
            print(f"[{i}] {oferta.titulo}")
            print(f"    Precio: Q{oferta.precio_gtq:,.2f}")
            print(f"    URL: {oferta.url}")
            print(f"    Imagen: {oferta.imagen_url}")
            print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())