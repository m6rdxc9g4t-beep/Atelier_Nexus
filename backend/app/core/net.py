"""Adresses locales et proxy système.

httpx lit le proxy de l'environnement (`trust_env`), et sous macOS et Windows `urllib`
y ajoute le proxy du **système** (réglages réseau, registre) sans ses exceptions : une requête
vers `http://127.0.0.1:8000` partait alors vers le proxy de l'entreprise, qui ne joint pas les
applications de la suite. Résultat : Atelier Viz « injoignable » alors qu'il tournait.

Règle : une adresse de bouclage (`127.0.0.1`, `localhost`, `::1`) est toujours jointe en
direct ; une adresse distante (GitHub, Supabase) garde le proxy de l'environnement.
"""

from __future__ import annotations

import ipaddress

import httpx

LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}


def is_loopback(url: str) -> bool:
    """Vrai si l'adresse (avec son schéma) désigne cette machine par le bouclage : rien ne sort
    de la machine. Strict : sert aussi de garde aux nœuds de la suite (app/suite/)."""
    try:
        host = httpx.URL(url).host
    except (httpx.InvalidURL, TypeError):
        return False
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def use_env_proxy(url: str) -> bool:
    """Valeur de `trust_env` pour un client httpx vers `url` : jamais de proxy en local.
    Accepte une adresse sans schéma (`localhost:11434`, forme admise par OLLAMA_HOST)."""
    text = url.strip()
    return not is_loopback(text if "://" in text else "http://" + text)
