"""Busca na web via DuckDuckGo (biblioteca ddgs, grátis e sem API key)."""
import logging

from ddgs import DDGS

log = logging.getLogger("hermes-bot.websearch")


def search(query, max_results=5):
    """Retorna (texto_formatado_com_fontes, erro). Um dos dois é None."""
    try:
        results = list(
            DDGS().text(query, region="br-pt", safesearch="moderate", max_results=max_results)
        )
    except Exception as e:
        log.warning("Busca falhou p/ '%s': %s", query, e)
        return None, f"erro ao buscar na web ({e.__class__.__name__})"

    if not results:
        return None, "nenhum resultado encontrado"

    blocos = []
    for i, r in enumerate(results, 1):
        titulo = (r.get("title") or "").strip()
        url = (r.get("href") or r.get("url") or "").strip()
        corpo = (r.get("body") or "").strip()
        blocos.append(f"[{i}] {titulo}\n{corpo}\nFonte: {url}")
    return "\n\n".join(blocos), None
