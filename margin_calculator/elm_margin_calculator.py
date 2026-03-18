#!/usr/bin/env python3

from __future__ import annotations
import csv
from collections import defaultdict
from typing import Dict, List
from datetime import datetime, timedelta
from span_parser import SPANParser, Instrument
from .redis_price_manager import RedisPriceManager


class ELMMarginCalculator:
    """
    Calculates the Exposure Margin using Exchange Level Margin (ELM) rates.

    This class loads symbol-specific ELM rates from a CSV file and provides
    the correct rate for a given instrument.
    """
    def __init__(self, elm_file_path: str, span_parser: SPANParser, redis_manager: RedisPriceManager, margin_calculator=None):
        """
        Initializes the ELMMarginCalculator.

        Args:
            elm_file_path (str): The path to the CSV file containing ELM rates.
            span_parser (SPANParser): The SPAN parser instance, used to access underlying prices.
            redis_manager (RedisPriceManager): The Redis manager for fetching underlying spot prices.
            margin_calculator: Reference to MarginCalculator for using get_notional_value method.
        """
        self.elm_rates = self._load_elm_rates(elm_file_path)
        self.instruments = span_parser.instruments
        self.redis_manager = redis_manager
        self.margin_calculator = margin_calculator

    def _load_elm_rates(self, elm_file_path: str) -> Dict[str, Dict[str, float]]:
        """Loads ELM rates from the provided CSV file."""
        elm_rates = defaultdict(dict)
        try:
            with open(elm_file_path, 'r') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    symbol = row.get('Symbol')
                    instrument_type = row.get('Instrument Type')
                    elm_percent = row.get('Total applicable ELM%')
                    if symbol and instrument_type and elm_percent:
                        elm_rates[symbol][instrument_type] = float(elm_percent) / 100.0
        except FileNotFoundError:
            print(f"Warning: ELM file not found at {elm_file_path}. Using default rates.")
        return elm_rates

    def get_elm_rate(self, instrument: Instrument, quantity: int, underlying_price: float = None) -> float:
        """
        Determines the appropriate ELM rate for a given instrument.

        ELM Rate Rules:
        - Calendar spread futures: 1/3 of far month position value
        - Short index options >10% OTM: 3%
        - Short index options >9 months maturity: 5%
        - Index derivatives (futures/options): 2%
        - Stock derivatives: Use AEL CSV rate (OTM if >10% OTM, else OTH) or default 3.5%
        """
        # Base rate for instruments
        stock_base_rate = 0.035
        index_base_rate = 0.02

        # Define Index Derivatives
        index_derivatives = ['BANKNIFTY', 'NIFTY', 'FINNIFTY', 'SENSEX', 'BANKEX', 'MIDCPNIFTY',]

        # Check if it's OTM (only for options)
        is_otm = False
        if (instrument.instrument_type in ('Call', 'Put') and
            instrument.strike_price):
            # Use provided underlying price or fetch from Redis
            if underlying_price is None:
                underlying_price = self.redis_manager.get_underlying_spot_price(instrument.name)
            
            if underlying_price:
                if instrument.name in index_derivatives:
                    # Index derivatives: 10% OTM
                    if instrument.instrument_type == 'Call' and instrument.strike_price > underlying_price * 1.1:
                        is_otm = True
                    elif instrument.instrument_type == 'Put' and instrument.strike_price < underlying_price * 0.9:
                        is_otm = True
                else:
                    # Stock derivatives: 30% OTM
                    if instrument.instrument_type == 'Call' and instrument.strike_price > underlying_price * 1.3:
                        is_otm = True
                    elif instrument.instrument_type == 'Put' and instrument.strike_price < underlying_price * 0.7:
                        is_otm = True

        # index options
        if instrument.name in index_derivatives:
            if quantity < 0:  # Short index options
                if is_otm:
                    return 0.03  # 3% ELM rate for OTM
                elif instrument.expiry_date and datetime.strptime(instrument.expiry_date, '%Y%m%d') > datetime.now() + timedelta(days=270):
                    return 0.05  # 5% ELM rate for long maturity
                else:
                    return index_base_rate  # Normal 2% rate
            else:
                return index_base_rate  # Normal 2% rate for long index options

        # Stock options - get rate from AEL file
        if (instrument.name not in index_derivatives and instrument.instrument_type in ('Call', 'Put')):
            # Get rate from AEL file
            csv_instrument_type = 'OTM' if is_otm else 'OTH'
            return self.elm_rates.get(instrument.name, {}).get(csv_instrument_type, stock_base_rate)

        # Handle futures (both index and stock) NOTE: Futures Calendar Spread Logic not here
        if instrument.instrument_type == 'Future':
            if instrument.name in index_derivatives:
                return index_base_rate  # 2% for index futures
            else:
                return stock_base_rate  # 3.5% for stock futures

        # Default fallback
        return stock_base_rate

    def calculate_total_exposure_margin(self, positions: List) -> float:
        """
        Calculates the total exposure margin for all positions in the portfolio.

        Exposure margin calculation rules:
        - For long options (buy): Zero exposure margin
        - For short options (sell): Use underlying spot price from Redis
        - For futures (both long and short): Use underlying spot price from Redis
        """
        total_exposure_margin = 0.0

        # Iterate through all positions
        for pos in positions:
            instrument = self.instruments.get(pos.instrument_code)
            if not instrument:
                continue

            # For long positions for options, exposure margin is zero
            if pos.quantity > 0 and instrument.instrument_type in ['Call', 'Put']:
                print(f"  Long position {instrument.code} (qty: {pos.quantity}) - Zero exposure margin")
                continue

            # For long futures and short positions (both futures and options)
            elif (pos.quantity > 0 and instrument.instrument_type == 'Future') or pos.quantity < 0:
                # Calculate exposure margin
                try:
                    # Get underlying price once to avoid redundant Redis calls
                    underlying_price = self.redis_manager.get_underlying_spot_price(instrument.name)
                    if underlying_price is None:
                        raise Exception(f"No underlying price found for {instrument.name}")

                    # Pass underlying price to both methods to avoid redundant Redis calls
                    underlying_prices = {instrument.name: underlying_price}
                    notional_value = self.margin_calculator.get_notional_value([pos], underlying_prices)
                    elm_rate = self.get_elm_rate(instrument, pos.quantity, underlying_price)
                    exposure_margin = notional_value * elm_rate

                    position_type = "Long" if pos.quantity > 0 else "Short"
                    print(f"  {position_type} position {instrument.code} (qty: {pos.quantity}) (elm rate: {elm_rate:.2%}) - Exposure margin: ₹{exposure_margin:,.2f}")
                    total_exposure_margin += exposure_margin

                except Exception as e:
                    print(f"  ERROR: {e}")
                    continue

        print(f"  Total exposure margin: ₹{total_exposure_margin:,.2f}")
        return total_exposure_margin
