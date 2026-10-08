from config import config
from brokers.base import BaseBroker


def get_broker(force_paper: bool = False) -> BaseBroker:
    if config.PAPER_TRADING or force_paper:
        from brokers.paper_broker import PaperBroker
        return PaperBroker()
    broker_map = {
        "ROBINHOOD": "brokers.robinhood.RobinhoodBroker",
        "WEBULL": "brokers.webull.WebullBroker",
        "TDAMERITRADE": "brokers.tdameritrade.TDAmeritradeBroker",
    }
    module_path = broker_map.get(config.BROKER)
    if not module_path:
        raise ValueError(f"Unknown broker: {config.BROKER}")
    module_name, class_name = module_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, class_name)()
