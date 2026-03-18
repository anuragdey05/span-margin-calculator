#!/usr/bin/env python3
"""
SPAN File Parser
Parses NSE SPAN XML files and extracts instrument data for margin calculations
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Instrument:
    """Represents a financial instrument with all SPAN risk parameters"""
    code: str                    # Unique instrument code
    name: str                    # Underlying symbol
    instrument_type: str         # Future, Call, Put
    currency: str               # Currency (INR)
    current_price: float        # Current market price from SPAN file
    conversion_factor: float = 1.0  # Lot size multiplier
    strike_price: Optional[float] = None  # Strike price for options
    expiry_date: Optional[str] = None     # Expiry date (YYYYMMDD format)
    delta: Optional[float] = None
    price_scan_rate: float = 0.0      # Price scan rate for risk calculation
    volatility_scan_rate: float = 0.0 # Volatility scan rate for risk calculation
    risk_array: Optional[List[float]] = None  # 16-element risk array for SPAN scenarios


class SPANParser:
    """Parses NSE SPAN XML files and extracts instrument data"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.instruments: Dict[str, Instrument] = {}

    def parse(self) -> Dict[str, Instrument]:
        """Main parsing method - extracts all instrument data from SPAN file"""
        print(f"Parsing SPAN file: {self.file_path}")

        tree = ET.parse(self.file_path)
        root = tree.getroot()

        self._parse_futures(root)
        self._parse_option_portfolios(root)

        print(f"Parsing complete. Found {len(self.instruments)} instruments")
        return self.instruments

    def _parse_futures(self, root):
        """Parse futures instruments from <futPf> elements"""
        for fut_pf in root.findall('.//futPf'):
            # Extract basic future data
            pf_code = fut_pf.findtext('pfCode', '')
            name = fut_pf.findtext('name', '')
            currency = fut_pf.findtext('currency', 'INR')

            # Find scan rate for this portfolio
            scan_rate = fut_pf.find('.//scanRate')
            price_scan_rate = 0.0
            volatility_scan_rate = 0.0
            if scan_rate is not None:
                price_scan_rate = float(scan_rate.findtext('priceScan', '0.0'))
                volatility_scan_rate = float(scan_rate.findtext('volScan', '0.0'))

            # Find all future elements within this portfolio
            for fut in fut_pf.findall('.//fut'):
                current_price = float(fut.findtext('p', '0.0'))
                expiry_date = fut.findtext('pe', '')

                # Extract risk array (16 scenarios)
                risk_array = []
                ra_elem = fut.find('ra')
                if ra_elem is not None:
                    for a_elem in ra_elem.findall('a'):
                        risk_value = float(a_elem.text or '0.0')
                        risk_array.append(risk_value)

                # Extract conversion factor (lot size)
                conversion_factor = float(fut_pf.findtext('cvf', '1.0'))
                instrument_code = f"{name}_FUTURE_{expiry_date}"

                instrument = Instrument(
                    code=instrument_code,
                    name=name,
                    instrument_type='Future',
                    currency=currency,
                    current_price=current_price,
                    expiry_date=expiry_date,
                    price_scan_rate=price_scan_rate,
                    volatility_scan_rate=volatility_scan_rate,
                    risk_array=risk_array,
                    conversion_factor=conversion_factor
                )

                self.instruments[instrument_code] = instrument

    def _parse_option_portfolios(self, root):
        """Parse option portfolios from <oopPf> elements"""
        for oop_pf in root.findall('.//oopPf'):
            # Extract basic option portfolio data
            pf_code = oop_pf.findtext('pfCode', '')
            name = oop_pf.findtext('name', '')
            currency = oop_pf.findtext('currency', 'INR')

            # Find scan rate for this portfolio
            scan_rate = oop_pf.find('.//scanRate')
            price_scan_rate = 0.0
            volatility_scan_rate = 0.0
            if scan_rate is not None:
                price_scan_rate = float(scan_rate.findtext('priceScan', '0.0'))
                volatility_scan_rate = float(scan_rate.findtext('volScan', '0.0'))

            # Extract conversion factor (at portfolio level)
            conversion_factor = float(oop_pf.findtext('cvf', '1.0'))

            # Find all series (expiries) within this portfolio
            for series in oop_pf.findall('series'):
                # Extract expiry date from this series
                expiry_date = series.findtext('pe', '')

                # Find all option elements within this series
                for opt in series.findall('opt'):
                    # Extract option-specific data
                    strike_price = float(opt.findtext('k', '0.0'))
                    current_price = float(opt.findtext('p', '0.0'))
                    option_type = 'Call' if opt.findtext('o', '') == 'C' else 'Put'

                    # Extract Greeks
                    delta = float(opt.findtext('d', '0.0'))

                    # Extract risk array (16 scenarios)
                    risk_array = []
                    ra_elem = opt.find('ra')
                    if ra_elem is not None:
                        for a_elem in ra_elem.findall('a'):
                            risk_value = float(a_elem.text or '0.0')
                            risk_array.append(risk_value)

                    # Create unique instrument code with expiry
                    strike_str = str(int(strike_price)) if strike_price.is_integer() else str(strike_price)
                    instrument_code = f"{name}_{option_type}_{strike_str}_{expiry_date}"

                    instrument = Instrument(
                        code=instrument_code,
                        name=name,
                        instrument_type=option_type,
                        currency=currency,
                        current_price=current_price,
                        strike_price=strike_price,
                        expiry_date=expiry_date,
                        delta=delta,
                        price_scan_rate=price_scan_rate,
                        volatility_scan_rate=volatility_scan_rate,
                        risk_array=risk_array,
                        conversion_factor=conversion_factor
                    )

                    self.instruments[instrument_code] = instrument
    def main():
        parser = SPANParser("span_files/nse_span_20250820.i01.spn")
        instruments = parser.parse()
        print(instruments)

    if __name__ == "__main__":
        main()