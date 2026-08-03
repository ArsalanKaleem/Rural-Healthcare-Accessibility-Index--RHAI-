import pandas as pd
from scipy.stats import spearmanr
g = pd.read_csv("data/pphi_geocode_review.csv")  # or recompute from the accepted set
a = pd.read_csv("data/rhai_layer_audit.csv")
# join per-district match rate to villages_per_1000km2, then:
# rho, p = spearmanr(match_rate, village_density)