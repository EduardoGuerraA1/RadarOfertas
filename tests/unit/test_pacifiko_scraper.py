from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.infrastructure.scrapers.pacifiko_scraper import PacifikoScraper

HTML_MUESTRA_PACIFIKO = """
<div class="products-list">
  <div class="product-layout product-grid"
       data-id="ZWE3YjA4Mj"
       data-name="Volante Y Pedales Logitech G923, Simulación de Carreras para PlayStation 4, 5 y PC">
    <div class="product-item-container">
      <div class="left-block">
        <div class="product-image-container">
          <a class="listing-product-link"
             href="/compras-en-linea/volante-y-pedales-logitech-g923&amp;pid=ZWE3YjA4Mj?ref=s&amp;query_id=1234"
             title="Volante Y Pedales Logitech G923, Simulación de Carreras para PlayStation 4, 5 y PC">
            <img class="lazyload img-responsive"
                 data-src="https://img.pacifiko.com/PROD/resize/1/250x250/ZWE3YjA4Mj_365.jpg" />
          </a>
        </div>
      </div>
      <div class="right-block title-block">
        <h4>
          <a class="listing-product-link"
             href="/compras-en-linea/volante-y-pedales-logitech-g923&amp;pid=ZWE3YjA4Mj?ref=s&amp;query_id=1234">
            Volante Y Pedales Logitech G923, Simulación de Carreras para Pl
          </a>
        </h4>
        <div class="price">
          <span class="price-new price-special">Q3,219.00</span>
          <span class="price-old">Q3,999.00</span>
        </div>
      </div>
    </div>
  </div>

  <div class="product-layout product-grid"
       data-id="MjJkZTk2Yz"
       data-name="Logitech G29 Driving Force - Juego de volante y pedales - cableado - para PC, Sony PlayStation 3, Sony PlayStation 4">
    <div class="product-item-container">
      <div class="left-block">
        <div class="product-image-container">
          <a class="listing-product-link"
             href="/compras-en-linea/logitech-g29-driving-force&amp;pid=MjJkZTk2Yz?ref=s&amp;query_id=1234">
            <img src="/PROD/resize/1/250x250/_1787449348.jpg" />
          </a>
        </div>
      </div>
      <div class="right-block title-block">
        <div class="price">
          <span class="price-new">
            Q3,295.01
            <meta content="Q" itemprop="priceCurrency"/>
          </span>
        </div>
      </div>
    </div>
  </div>

  <div class="product-layout product-grid" data-name="Producto agotado sin precio">
    <a class="listing-product-link" href="/compras-en-linea/agotado">Agotado</a>
  </div>
</div>
"""


def test_parsear_html_busqueda_pacifiko_extrae_ofertas_validas():
    ofertas = PacifikoScraper.parsear_html_busqueda(HTML_MUESTRA_PACIFIKO)

    assert len(ofertas) == 2
    assert all(isinstance(o, OfertaLocal) for o in ofertas)

    primera = ofertas[0]
    assert primera.tienda == "Pacifiko"
    assert (
        primera.titulo
        == "Volante Y Pedales Logitech G923, Simulación de Carreras para PlayStation 4, 5 y PC"
    )
    assert primera.precio_gtq == 3219.00
    assert (
        primera.url
        == "https://www.pacifiko.com/compras-en-linea/volante-y-pedales-logitech-g923&pid=ZWE3YjA4Mj"
    )
    assert (
        primera.imagen_url
        == "https://img.pacifiko.com/PROD/resize/1/250x250/ZWE3YjA4Mj_365.jpg"
    )

    segunda = ofertas[1]
    assert segunda.precio_gtq == 3295.01
    assert (
        segunda.imagen_url
        == "https://www.pacifiko.com/PROD/resize/1/250x250/_1787449348.jpg"
    )


def test_parsear_html_vacio_retorna_lista_vacia():
    assert PacifikoScraper.parsear_html_busqueda("") == []
