"""Free-data Wimbledon ratings pipeline.

A one-off ETL that turns free open tennis datasets into editorial 0-100 grass
ratings (serve, return, forehand, backhand, net_volley, consistency) for the
top ~50 most-notable men and women of 2006-2025 (configurable), on a
career/peak-grass basis.

See README.md for the full design, licensing notes and run instructions.
"""

__version__ = "0.1.0"
