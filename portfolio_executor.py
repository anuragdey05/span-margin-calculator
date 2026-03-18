
import csv
from typing import List, Dict
from datetime import datetime
from span_parser import SPANParser
from margin_calculator import MarginCalculator, RedisPriceManager, Position



def load_portfolio_from_detailed_csv(file_path: str, instruments: Dict[str, object]) -> List[Position]:
    """
    Loads a portfolio from detailed CSV (like 'sample_portfolio .csv') with columns:
    product_type,symbol,expiry,net_qty,option_type,strike,buy/sell

    Validates that the requested expiry matches SPAN data; if not, the row is skipped
    and available expiries are shown.
    """
    positions: List[Position] = []
    mismatches: List[Dict[str, str]] = []
    try:
        with open(file_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    product_type = row['product_type'].strip().lower()
                    symbol = row['symbol'].strip()
                    csv_expiry_str = row.get('expiry', '').strip()
                    net_qty = int(row['net_qty'])
                    direction = row.get('buy/sell', '').strip().lower()

                    # Convert buy/sell to signed quantity if net_qty is unsigned
                    if net_qty > 0 and direction == 'sell':
                        net_qty = -net_qty

                    # Build expiry-aware code: YYYYMMDD
                    csv_expiry_span_fmt = None
                    if csv_expiry_str:
                        try:
                            csv_expiry_span_fmt = datetime.strptime(csv_expiry_str, "%d-%b-%y").strftime("%Y%m%d")
                        except ValueError:
                            pass
                    expiry_part = csv_expiry_span_fmt or ''


                    strike_str = None # For validation message

                    if product_type == 'future':
                        instrument_code = f"{symbol}_FUTURE_{expiry_part}"

                    elif product_type == 'option':
                        opt_type = row['option_type'].strip()
                        strike = row['strike'].strip()
                        # Normalize strike to match SPAN parser format (int if whole number)
                        try:
                            strike_val = float(strike)
                            strike_str = str(int(strike_val)) if strike_val.is_integer() else str(strike_val)
                        except ValueError:
                            strike_str = strike
                        instrument_code = f"{symbol}_{opt_type}_{strike_str}_{expiry_part}"
                    else:
                        print(f"Unknown product_type in row; skipping: {row}")
                        continue

                    # Validate existence
                    inst = instruments.get(instrument_code)
                    if not inst:
                        # Find available expiries for this symbol+type+strike
                        available_expiries = set()

                        validation_prefix = f"{symbol}_"
                        if product_type == 'option':
                            validation_prefix += f"{opt_type}_{strike_str}_"
                        elif product_type == 'future':
                            validation_prefix += "FUTURE_"

                        for code, i in instruments.items():
                            if code.startswith(validation_prefix) and getattr(i, 'expiry_date', None):
                                try:
                                    d = datetime.strptime(i.expiry_date, "%Y%m%d").strftime("%d-%b-%y")
                                except Exception:
                                    d = i.expiry_date
                                available_expiries.add(d)

                        # If a specific expiry was requested, list which strikes DO exist for that expiry
                        available_strikes_for_expiry = set()
                        if csv_expiry_span_fmt:
                            for code, i in instruments.items():
                                if code.startswith(f"{symbol}_{opt_type}_") and getattr(i, 'expiry_date', None) == csv_expiry_span_fmt:
                                    # Extract strike from code or use i.strike_price
                                    try:
                                        s_val = int(i.strike_price) if float(i.strike_price).is_integer() else float(i.strike_price)
                                        available_strikes_for_expiry.add(str(s_val))
                                    except Exception:
                                        pass

                        mismatches.append({
                            'symbol': symbol,
                            'requested': csv_expiry_str,
                            'instrument_code': instrument_code,
                            'reason': 'instrument not found',
                            'available_expiries': ", ".join(sorted(available_expiries)) or 'none',
                            'available_strikes_for_requested_expiry': ", ".join(sorted(available_strikes_for_expiry)) or 'none'
                        })
                        continue

                    # Validate expiry if provided for options
                    if product_type == 'option' and csv_expiry_str and inst:
                        try:
                            csv_expiry_span_fmt = datetime.strptime(csv_expiry_str, "%d-%b-%y").strftime("%Y%m%d")
                        except ValueError:
                            csv_expiry_span_fmt = None
                        inst_expiry = getattr(inst, 'expiry_date', None)
                        if csv_expiry_span_fmt and inst_expiry and csv_expiry_span_fmt != inst_expiry:
                            # Collect available expiries for same symbol and type
                            available_expiries = set()
                            for code, i in instruments.items():
                                if code.startswith(f"{symbol}_{opt_type}_{strike_str}_") and getattr(i, 'expiry_date', None):
                                    try:
                                        d = datetime.strptime(i.expiry_date, "%Y%m%d").strftime("%d-%b-%y")
                                    except Exception:
                                        d = i.expiry_date
                                    available_expiries.add(d)
                            mismatches.append({
                                'symbol': symbol,
                                'requested': csv_expiry_str,
                                'found': inst_expiry,
                                'instrument_code': instrument_code,
                                'reason': 'expiry mismatch',
                                'available_expiries': ", ".join(sorted(available_expiries)) or 'none'
                            })
                            continue

                    quantity = abs(net_qty)
                    if direction == 'sell':
                        quantity = -quantity

                    positions.append(Position(instrument_code=instrument_code, quantity=quantity))
                except Exception as e:
                    print(f"Skipping row due to error: {row} Error: {e}")
    except FileNotFoundError:
        print(f"Detailed portfolio file not found at {file_path}. Returning empty portfolio.")
        return []

    if mismatches:
        print("\nThe following portfolio rows were skipped due to validation errors:")
        for m in mismatches:
            if m['reason'] == 'expiry mismatch':
                try:
                    found_readable = datetime.strptime(m['found'], "%Y%m%d").strftime("%d-%b-%y") if m.get('found') else 'unknown'
                except Exception:
                    found_readable = m.get('found', 'unknown')
                print(f"- {m['instrument_code']}: requested expiry {m['requested']} but SPAN has {found_readable}. Available: {m['available_expiries']}")
            else:
                print(f"- {m['instrument_code']}: not found in SPAN. Requested expiry {m['requested']}.")
                print(f"  Available expiries for same strike: {m.get('available_expiries','none')}")
                if m.get('available_strikes_for_requested_expiry'):
                    print(f"  Strikes available for {m['requested']}: {m['available_strikes_for_requested_expiry']}")
        print("Fix the CSV expiries or symbols and re-run.")
        # Abort calculation to avoid misleading results
        return []

    return positions


def display_margin_results(results, individual_margins, positions, instruments):
    """Display the margin calculation results like Zerodha's format"""

    # Calculate total individual margins for comparison
    total_individual_span = sum(margin['span_margin'] for margin in individual_margins.values())
    total_individual_exposure = sum(margin['exposure_margin'] for margin in individual_margins.values())
    total_individual_premium = sum(margin['premium_receivable'] for margin in individual_margins.values())
    total_individual_margin = sum(margin['total_margin'] for margin in individual_margins.values())

    # Calculate margin benefit
    margin_benefit = total_individual_margin - results.total_margin

    print()
    print("=== INDIVIDUAL MARGIN REQUIREMENTS ===")
    print(f"{'Exchange':<10} {'Contract':<20} {'Product':<8} {'Strike':<8} {'Qty':<5} {'Buy/Sell':<8} {'SPAN':<10} {'Exposure':<10} {'Total':<10}")
    print("-" * 93)

    for pos in positions:
        instrument = instruments.get(pos.instrument_code)
        if instrument:
            individual = individual_margins[pos.instrument_code]

            # Dynamically format the contract name from the instrument's expiry date
            try:
                expiry_dt = datetime.strptime(instrument.expiry_date, "%Y%m%d")
                contract_expiry_str = expiry_dt.strftime("%d%b%y").upper()
            except (ValueError, TypeError):
                contract_expiry_str = instrument.expiry_date # Fallback

            contract = f"{instrument.name}{contract_expiry_str}"

            if instrument.instrument_type == 'Future':
                product = "Futures"
                strike = "N/A"
            else:
                product = "Options"
                option_suffix = "CE" if instrument.instrument_type == "Call" else "PE"
                strike = f"{instrument.strike_price:.0f} {option_suffix}"

            # Determine buy/sell direction
            direction = "SELL" if pos.quantity < 0 else "BUY"

            print(f"{'NFO':<10} {contract:<20} {product:<8} {strike:<8} {abs(pos.quantity):<5} {direction:<8} {individual['span_margin']:>10,.0f} {individual['exposure_margin']:>10,.0f} {individual['total_margin']:>10,.0f}")

    print("-" * 93)
    print(f"{'TOTAL':<10} {'':<20} {'':<8} {'':<8} {'':<5} {'':<8} {total_individual_span:>10,.0f} {total_individual_exposure:>10,.0f} {total_individual_margin:>10,.0f}")

    print()
    print("=== COMBINED MARGIN REQUIREMENTS ===")
    print(f"SPAN Margin:              ₹{results.span_risk_requirement:>10,.0f}")
    print(f"Exposure Margin:          ₹{results.exposure_margin:>10,.0f}")
    print(f"Premium Receivable:       ₹{results.premium_receivable:>10,.0f}")
    print(f"Total Margin:             ₹{results.total_margin:>10,.0f}")
    print()
    print(f"Margin Benefit:           ₹{margin_benefit:>10,.0f}")
    print("=" * 50)


def main():
    """
    The main execution function for the margin calculation process.
    """
    # --- Configuration ---
    SPAN_FILE_PATH = "span_files/nsccl.20250820.i01.spn"
    ELM_FILE_PATH = "span_files/ael_20082025.csv"
    # Use provided CSV with space in name
    DETAILED_PORTFOLIO_FILE_PATH = "sample_portfolio .csv"
    REDIS_HOST = "127.0.0.1"
    REDIS_PORT = 6379

    # 1. Initialize the SPAN Parser and parse the file
    print(f"Loading SPAN file from {SPAN_FILE_PATH}...")
    span_parser = SPANParser(SPAN_FILE_PATH)
    span_parser.parse()

    # 2. Initialize the Redis Price Manager
    print(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT}...")
    try:
        redis_manager = RedisPriceManager(host=REDIS_HOST, port=REDIS_PORT)
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return

    # 3. Initialize the main Margin Calculator
    print("Initializing Margin Calculator...")
    margin_calculator = MarginCalculator(span_parser, redis_manager, ELM_FILE_PATH)

    # 4. Load the portfolio from the detailed CSV file with validation
    print(f"Loading portfolio from {DETAILED_PORTFOLIO_FILE_PATH}...")
    portfolio = load_portfolio_from_detailed_csv(DETAILED_PORTFOLIO_FILE_PATH, span_parser.instruments)

    if not portfolio:
        print("Portfolio is empty after validation. No calculations to perform.")
        return

    print(f"Portfolio loaded with {len(portfolio)} positions.")
    for pos in portfolio:
        print(f"  - {pos.instrument_code}, Quantity: {pos.quantity}")

    # 5. Calculate individual margins for each position
    print("\nCalculating individual margins...")
    individual_margins = {}
    for pos in portfolio:
        individual_margins[pos.instrument_code] = margin_calculator.calculate_individual_margin(pos)

    # 6. Run the portfolio margin calculation
    print("Calculating combined portfolio margin...")
    margin_results = margin_calculator.calculate_portfolio_margin(portfolio)

    # 7. Display the results
    display_margin_results(margin_results, individual_margins, portfolio, span_parser.instruments)


if __name__ == "__main__":
    main()
