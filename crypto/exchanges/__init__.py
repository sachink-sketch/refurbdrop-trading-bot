from crypto.crypto_config import crypto_config
from crypto.exchanges.base_exchange import BaseCryptoExchange


def get_exchange(force_paper: bool = False) -> BaseCryptoExchange:
    if crypto_config.EXCHANGE == "PAPER" or force_paper:
        from crypto.exchanges.paper_exchange import PaperCryptoExchange
        return PaperCryptoExchange(crypto_config.PAPER_STARTING_USDT)
    from crypto.exchanges.live_exchange import LiveCryptoExchange
    return LiveCryptoExchange(
        crypto_config.EXCHANGE,
        crypto_config.EXCHANGE_API_KEY,
        crypto_config.EXCHANGE_API_SECRET,
        crypto_config.EXCHANGE_PASSPHRASE,
    )
