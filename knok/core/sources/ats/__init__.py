"""Lectores de ATS con API pública de ofertas."""
from knok.core.sources.ats import ashby, greenhouse, lever

FETCHERS = {"greenhouse": greenhouse.fetch_board, "lever": lever.fetch_board, "ashby": ashby.fetch_board}
