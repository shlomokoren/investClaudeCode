import os

from flask import Flask

from blueprints.financials import financials_bp
from blueprints.price import price_bp

app = Flask(__name__)
app.register_blueprint(price_bp)
app.register_blueprint(financials_bp)


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("DEBUG", "true").lower() == "true",
    )
