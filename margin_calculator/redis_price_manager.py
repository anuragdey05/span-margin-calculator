#!/usr/bin/env python3

from __future__ import annotations
import redis
from typing import Optional
from datetime import datetime

from span_parser import Instrument


class RedisPriceManager:
    """
    Manages connections to Redis for fetching prices.
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 6379, db: int = 0):
        """
        Initializes the class and establishes connection to Redis.

        Args:
            host (str): Redis server hostname
            port (int): Redis server port
            db (int): Redis database number
        """
        try:
            # Connecting to Redis
            self.redis_client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
            self.redis_client.ping()
            print("✅ Redis connection successful.")

        except redis.exceptions.ConnectionError as e:
            print(f"❌ Redis connection failed: {e}")
            raise ConnectionError(f"Failed to connect to Redis at {host}:{port} (db {db}).") from e

    def get_option_price_for_instrument(self, instrument: Instrument) -> Optional[float]:
        """
        Fetches the previous day closing price for an option instrument from Redis.

        Args:
            instrument: The option instrument to get price for

        Returns:
            float: The option price, or None if not found/invalid
        """
        # Build Redis key: market:latest:{UNDERLYING}{YY}{MMM}{STRIKE}{CE|PE}
        expiry = datetime.strptime(instrument.expiry_date, "%Y%m%d")
        expiry_str = f"{expiry.strftime('%y')}{expiry.strftime('%b').upper()}"
        strike_str = str(int(instrument.strike_price))
        option_type = "CE" if instrument.instrument_type == "Call" else "PE"
        redis_key = f"market:latest:{instrument.name}{expiry_str}{strike_str}{option_type}"

        print(f"  Querying Redis key: {redis_key}")

        try:
            # Get the hash data
            price_data = self.redis_client.hgetall(redis_key)

            if not price_data:
                print(f"  - Key not found in Redis.")
                return None

            close_price = price_data.get('close')
            if close_price:
                try:
                    price = float(close_price)
                    if price > 0:
                        print(f"  - Price found: {price}")
                        return price
                    else:
                        print(f"  - Price is zero or negative: {price}")
                except (ValueError, TypeError):
                    print(f"  - Could not convert 'close' to float: {close_price}")
            else:
                print(f"  - 'close' field not found in data: {price_data}")

        except redis.exceptions.RedisError as e:
            print(f"  - Redis error: {e}")

        return None

    def get_underlying_spot_price(self, underlying_name: str) -> Optional[float]:
        """
        Fetches the current spot price for an underlying from Redis.
        Data is stored as a Redis hash with format: market:latest:{UNDERLYING}
        """

        # Handle special cases for underlying names
        redis_underlying_name = underlying_name
        if underlying_name == "NIFTY":
            redis_underlying_name = "NIFTY50"
        elif underlying_name == "MIDCPNIFTY":
            redis_underlying_name = "NIFTYMIDCAP50"  # Redis key format

        # Format: market:latest:{UNDERLYING}
        redis_key = f"market:latest:{redis_underlying_name}"
        print(f"  Querying Redis key for underlying spot: {redis_key}")

        try:
            if not self.redis_client.exists(redis_key):
                print(f"  - Underlying spot key not found in Redis.")
                return None

            # Get the hash data
            price_data = self.redis_client.hgetall(redis_key)

            if price_data and 'last_price' in price_data and price_data['last_price'] is not None:
                try:
                    price = float(price_data['last_price'])
                    if price > 0:
                        print(f"  - Underlying spot price found: {price}")
                        return price
                    else:
                        print(f"  - Underlying spot price is zero or negative: {price}")
                except (ValueError, TypeError):
                    print(f"  - Could not convert 'last_price' to float: {price_data['last_price']}")
            else:
                print(f"  - 'last_price' field not found in data: {price_data}")

        except redis.exceptions.RedisError as e:
            print(f"  - Redis error: {e}")

        return None
