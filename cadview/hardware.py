"""cadview.hardware -> openworkshop.hardware (the project was renamed; see cadview/__init__.py)."""
import openworkshop.hardware as _m

globals().update({k: v for k, v in vars(_m).items() if k not in ("__name__", "__file__", "__spec__", "__loader__", "__package__")})
