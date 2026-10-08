"""cadview.server -> openworkshop.server (the project was renamed; see cadview/__init__.py)."""
import openworkshop.server as _m

globals().update({k: v for k, v in vars(_m).items() if k not in ("__name__", "__file__", "__spec__", "__loader__", "__package__")})

if __name__ == "__main__":
    _m.main()
