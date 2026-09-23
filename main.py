import asyncio
import logging
from src.radar_ofertas.scrapers.kemik import KemikScraper  # Ajusta la ruta según tu estructura real

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RadarOfertasMain")

async def ejecutar_prueba_orquestador(termino: str):
    logger.info(f"Iniciando orquestador para el término de búsqueda: '{termino}'")
    
    scraper = KemikScraper()
    
    try:
        ofertas = await scraper.buscar(termino)
        
        print("\n" + "=" * 80)
        print(f" RESULTADOS DEL RADAR - KEMIK | Búsqueda: '{termino}'")
        print(f" Total de ofertas encontradas: {len(ofertas)}")
        print("=" * 80)
        
        if not ofertas:
            print("No se encontraron ofertas para este término.")
            return

        for i, oferta in enumerate(ofertas, 1):
            # Asumiendo que tu objeto OfertaLocal o diccionario tiene estos atributos/claves
            titulo = getattr(oferta, 'titulo', oferta.get('titulo'))
            precio = getattr(oferta, 'precio', oferta.get('precio'))
            url = getattr(oferta, 'url', oferta.get('url'))
            imagen = getattr(oferta, 'imagen', oferta.get('imagen'))
            
            print(f"[{i}] {titulo}")
            print(f"    Precio : Q{precio}")
            print(f"    URL    : {url}")
            print(f"    Imagen : {imagen}")
            print("-" * 80)

    except Exception as e:
        logger.error(f"Error crítico en el orquestador: {e}")

if __name__ == "__main__":
    termino_prueba = "teclado"
    asyncio.run(ejecutar_prueba_orquestador(termino_prueba))