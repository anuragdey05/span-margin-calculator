#!/usr/bin/env python3

from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
from typing import Dict, List, Optional, Any

from span_parser import SPANParser, Instrument
from .redis_price_manager import RedisPriceManager
from .elm_margin_calculator import ELMMarginCalculator

index_underlyings = ['BANKNIFTY', 'NIFTY', 'FINNIFTY', 'SENSEX', 'BANKEX', 'MIDCPNIFTY']

@dataclass
class Position:
    """
    Represents a single trading position in a portfolio.

    Attributes:
        instrument_code (str): The unique code for the instrument.
        quantity (int): The number of units of the instrument.
                        Positive for long positions, negative for short positions.
    """
    instrument_code: str
    quantity: int


@dataclass
class PortfolioMarginResult:
    """Minimal portfolio margin result used for output."""
    span_risk_requirement: float
    calendar_spread_charge: float
    total_span_margin: float
    exposure_margin: float
    net_option_value: float
    premium_receivable: float
    total_margin: float
    group_details: Dict[str, Any]


class MarginCalculator:
    """
    The main engine for calculating all components of margin requirements.

    This class brings together the SPAN data, ELM rates, and real-time Redis prices
    to compute a comprehensive margin report for a given portfolio.
    """

    def __init__(self, span_parser: SPANParser, redis_manager: RedisPriceManager, elm_file_path: str):
        """
        Initializes the MarginCalculator.

        Args:
            span_parser (SPANParser): An instance of the SPAN parser with loaded instrument data.
            redis_manager (RedisPriceManager): An instance of the manager for fetching Redis prices.
            elm_file_path (str): The path to the CSV file containing ELM rates.
        """
        self.parser = span_parser
        self.instruments = span_parser.instruments
        self.redis_manager = redis_manager
        self.elm_calculator = ELMMarginCalculator(elm_file_path, span_parser, redis_manager, self)

    def calculate_net_option_value(self, positions: List[Position]) -> float:
        """
        Calculates the Net Option Value (NOV) for positions in the same underlying.
        NOV = LOV - SOV
        - LOV (Long Option Value): Sum of all long option positions
        - SOV (Short Option Value): Sum of all short option positions

        Args:
            positions (List[Position]): A list of the positions in the same underlying.

        Returns:
            float: The calculated Net Option Value (LOV - SOV).
        """
        long_option_value = 0.0
        short_option_value = 0.0

        for pos in positions:
            instrument = self.instruments.get(pos.instrument_code)
            if not instrument or instrument.instrument_type not in ['Call', 'Put']:
                continue

            # Get price from Redis
            price = self.redis_manager.get_option_price_for_instrument(instrument)

            # Long position
            if pos.quantity > 0:
                option_value = abs(pos.quantity) * price * instrument.conversion_factor
                long_option_value += option_value
                print(f"  LOV: {instrument.code} (qty: {pos.quantity}) = ₹{option_value:,.2f}")
            # Short position
            elif pos.quantity < 0:
                option_value = abs(pos.quantity) * price * instrument.conversion_factor
                short_option_value += option_value
                print(f"  SOV: {instrument.code} (qty: {pos.quantity}) = ₹{option_value:,.2f}")

        print(f"  Total LOV: ₹{long_option_value:,.2f}")
        print(f"  Total SOV: ₹{short_option_value:,.2f}")
        print(f"  NOV (LOV - SOV): ₹{long_option_value - short_option_value:,.2f}")

        return long_option_value - short_option_value

    def calculate_calendar_spread_charge(self, positions: List[Position]) -> float:
        """
        Calculates the calendar spread charge of each group.
        The spread benefit exists only until the near-month expiry.

        Args:
            positions (List[Position]): The list of positions in the portfolio.

        Returns:
            float: The calculated calendar spread charge.
        NOTE: Residual delta calculation is not fully implemented but assumed because of insufficient documentation on the same.
        """
        if not positions:
            return 0.0

        # Check if more than 1 month exists in the underlying group
        month_groups = defaultdict(list)
        for pos in positions:
            instrument = self.instruments.get(pos.instrument_code)
            if instrument and instrument.expiry_date:
                expiry_month = instrument.expiry_date[:6]  # YYYYMM
                # Creating a list of the months and the positions in that month
                month_groups[expiry_month].append((pos, instrument))

        if len(month_groups) <= 1:
            print(f"  Calendar spread: Skipped (only {len(month_groups)} month(s) found)")
            return 0.0

        print(f"  Calendar spread: Processing {len(month_groups)} months")
        # More than 1 month so will calculate calendar spread
        total_spread_charge = 0.0

        # Get underlying name from first position
        first_instrument = self.instruments.get(positions[0].instrument_code)
        if not first_instrument:
            return 0.0

        underlying_name = first_instrument.name

        # Step A: Convert positions into delta equivalents
        # Step B: Calculate net delta for each contract month
        month_deltas = {}
        for month, month_positions in month_groups.items():
            net_delta = 0.0
            for pos, instrument in month_positions:
                if instrument.instrument_type == 'Future':
                    # Futures: delta = +1 (long future), -1 (short future) per unit
                    position_delta = pos.quantity
                    net_delta += position_delta
                elif instrument.instrument_type in ['Call', 'Put'] and instrument.delta is not None:
                    # Options: delta = option delta × net quantity
                    position_delta = pos.quantity * instrument.delta
                    net_delta += position_delta
            month_deltas[month] = net_delta

        # Sort the months by date (near to far)
        sorted_months = sorted(month_deltas.keys())

        # Step C: Form calendar spreads and apply spread charges
        residual_delta = 0.0  # Track residual delta from previous iteration

        for i in range(len(sorted_months) - 1):
            near_month = sorted_months[i]
            far_month = sorted_months[i + 1]

            # Use residual delta from previous iteration as near month delta
            if i == 0:
                near_delta = month_deltas[near_month]
            else:
                near_delta = residual_delta

            far_delta = month_deltas[far_month]

            if (near_delta > 0 and far_delta < 0) or (near_delta < 0 and far_delta > 0):
                # Calculate matched units (smaller absolute delta)
                matched_units = min(abs(near_delta), abs(far_delta))

                if matched_units > 0:
                    print(f"  Spread {near_month}-{far_month}: {matched_units:.2f} units matched")
                    # Extract positions for far month
                    far_month_positions = [pos for pos, _ in month_groups[far_month]]

                    # Calculate far month notional value using get_notional_value method
                    far_month_notional = self.get_notional_value(far_month_positions)

                    # Apply spread rate based on underlying type
                    if underlying_name in index_underlyings:
                        spread_rate = 0.0175  # 1.75% for index derivatives
                    else:
                        spread_rate = 0.022   # 2.2% for stock derivatives

                    # Calculate spread charge for this pair
                    spread_charge = far_month_notional * spread_rate
                    total_spread_charge += spread_charge
                    print(f"    Notional: ₹{far_month_notional:,.0f}, Rate: {spread_rate:.1%}, Charge: ₹{spread_charge:,.0f}")

            # Calculate residual delta for next iteration
            residual_delta = near_delta + far_delta
            print(f"    Residual delta for next iteration: {residual_delta:+.2f}")
        if total_spread_charge == 0.0:
            print(f"  Calendar spread: No valid spreads formed")

        print(f"  Total calendar spread charge: ₹{total_spread_charge:,.0f}")
        return total_spread_charge


    def get_notional_value(self, positions: List[Position], underlying_prices: Dict[str, float] = None) -> float:
        """
        Calculates the total notional value of positions.

        Notional value = underlying_price × quantity × conversion_factor
        This represents the total market value of the positions.

        Args:
            positions (List[Position]): List of positions to calculate notional for

        Returns:
            float: Total notional value in rupees
        """
        total_notional = 0.0

        for pos in positions:
            instrument = self.instruments.get(pos.instrument_code)
            if not instrument:
                raise Exception(f"Instrument not found for code {pos.instrument_code}")

            underlying_name = instrument.name
            # Use provided underlying price or fetch from Redis
            if underlying_prices and underlying_name in underlying_prices:
                underlying_price = underlying_prices[underlying_name]
            else:
                underlying_price = self.redis_manager.get_underlying_spot_price(underlying_name)

            if underlying_price is None:
                raise Exception(f"No underlying price found for {underlying_name}")

            # Calculate notional value with conversion factor
            position_notional = underlying_price * abs(pos.quantity) * instrument.conversion_factor
            total_notional += position_notional

        return total_notional

    def calculate_span_risk_requirement(self, positions: List[Position]) -> float:
        """
        Calculates the maximum SPAN risk (worst-case scenario loss) for a set of positions in the same underlying.

        Args:
            positions (List[Position]): Positions for a single underlying.
        Returns:
            float: Maximum SPAN risk requirement.
        """
        if not positions:
            return 0.0

        # Aggregate the risk arrays of all positions in the underlying group
        portfolio_risk_array = [0.0] * 16

        for pos in positions:
            instrument = self.parser.instruments.get(pos.instrument_code)
            if not instrument or not instrument.risk_array or len(instrument.risk_array) < 16:
                continue

            # Fetch the standard risk array (for a long position)
            base_risk_array = instrument.risk_array

            # If position is short, invert the array (multiply by -1)
            if pos.quantity < 0:
                adjusted_risk_array = [-val for val in base_risk_array]
            else:
                adjusted_risk_array = base_risk_array

            for i in range(16):
                # Multiply by absolute position size and add to portfolio scenarios
                scenario_loss = adjusted_risk_array[i] * abs(pos.quantity) * instrument.conversion_factor
                portfolio_risk_array[i] += scenario_loss

        # The SPAN risk is the maximum loss among the 16 scenarios
        worst_case_loss = max(portfolio_risk_array)

        # If the computed margin is negative (i.e., no loss), set Scan Risk = 0
        return max(0.0, worst_case_loss)

    def calculate_individual_margin(self, position: Position) -> Dict[str, float]:
        """
        Calculate margin requirements for a single position precisely as specified.
        """
        instrument = self.parser.instruments.get(position.instrument_code)
        if not instrument or not instrument.risk_array or len(instrument.risk_array) < 16:
            return {'span_margin': 0, 'exposure_margin': 0, 'premium_receivable': 0, 'total_margin': 0}
        # For long options, SPAN and exposure margin are zero.
        if instrument.instrument_type in ['Call', 'Put'] and position.quantity > 0:
            individual_span = 0.0
            individual_exposure = 0.0
        else:
            # SPAN Margin Calculation
            individual_span = self.calculate_span_risk_requirement([position])
            # Exposure Margin Calculation
            individual_exposure = self.elm_calculator.calculate_total_exposure_margin([position])

        # Individual premium receivable (for short options)
        individual_premium = self.calculate_premium_receivable([position])

        # Individual total margin
        individual_total = individual_span + individual_exposure
        return {
            'span_margin': individual_span,
            'exposure_margin': individual_exposure,
            'premium_receivable': individual_premium,
            'total_margin': individual_total
        }

    def calculate_portfolio_margin(self, positions: List[Position]) -> PortfolioMarginResult:
        """
        Calculates the complete, final margin for the entire portfolio.
        Groups positions by underlying and calculates SPAN margin for each underlying separately.
        """
        # Group positions by underlying
        underlying_groups = {}
        for pos in positions:
            instrument = self.instruments.get(pos.instrument_code)
            if instrument:
                underlying_name = instrument.name
                if underlying_name not in underlying_groups:
                    underlying_groups[underlying_name] = []
                underlying_groups[underlying_name].append(pos)

        # Calculate SPAN margin for each underlying
        total_span_risk_req = 0.0
        total_span_margin = 0.0
        total_calendar_spread = 0.0
        total_nov = 0.0
        group_details = {}

        for underlying_name, underlying_positions in underlying_groups.items():
            print(f"\n📊 Calculating SPAN margin for {underlying_name}")
            print(f"   Positions: {len(underlying_positions)}")

            # Calculate components for this underlying
            span_risk_req = self.calculate_span_risk_requirement(underlying_positions)
            calendar_spread = self.calculate_calendar_spread_charge(underlying_positions)
            net_option_value = self.calculate_net_option_value(underlying_positions)

            # Calculate total SPAN margin for this underlying
            underlying_span_margin = span_risk_req + calendar_spread - net_option_value
            underlying_span_margin = max(0, underlying_span_margin)

            #Calculate totals
            total_span_risk_req += span_risk_req
            total_calendar_spread += calendar_spread
            total_nov += net_option_value

            # Printing logs of each group
            print(f"   SPAN Risk: ₹{span_risk_req:,.2f}")
            print(f"   Calendar Spread: ₹{calendar_spread:,.2f}")
            print(f"   NOV: ₹{net_option_value:,.2f}")
            print(f"   Total SPAN Margin: ₹{underlying_span_margin:,.2f}")

            # Store group details
            group_details[underlying_name] = {
                'span_risk_requirement': span_risk_req,
                'calendar_spread_charge': calendar_spread,
                'net_option_value': net_option_value,
                'total_span_margin': underlying_span_margin,
                'position_count': len(underlying_positions)
            }

        #Calculate total span margin
        total_span_margin = total_span_risk_req + total_calendar_spread - total_nov

        # Calculate exposure margin and premium receivable for entire portfolio
        exposure = self.elm_calculator.calculate_total_exposure_margin(positions)
        premium_receivable = self.calculate_premium_receivable(positions)

        # Calculate total margin
        total_margin = total_span_margin + exposure
        total_margin = max(0, total_margin)

        return PortfolioMarginResult(
            span_risk_requirement=total_span_margin,
            calendar_spread_charge=total_calendar_spread,
            total_span_margin=total_span_margin,
            exposure_margin=exposure,
            net_option_value=total_nov,
            premium_receivable=premium_receivable,
            total_margin=total_margin,
            group_details=group_details
        )

    def calculate_premium_receivable(self, positions: List[Position]) -> float:
        """
        Calculates the total premium received from selling options.
        """
        total_premium = 0.0
        for pos in positions:
            if pos.quantity < 0:  # Only for short positions
                instrument = self.parser.instruments.get(pos.instrument_code)
                if instrument and instrument.instrument_type in ['Call', 'Put']:
                    price = self.redis_manager.get_option_price_for_instrument(instrument)
                    if price is not None:
                        total_premium += abs(pos.quantity) * price * instrument.conversion_factor
                    else:
                        raise Exception(f"No price found for {instrument.code}")

        return total_premium
