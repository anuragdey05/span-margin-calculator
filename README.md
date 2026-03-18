# SPAN Margin Calculator Documentation for Bullero Capital Internship 2025

This calculator implements the SPAN (Standard Portfolio Analysis of Risk) methodology as per NSE guidelines for calculating margin requirements for derivatives portfolios.

## Overview

The SPAN Margin Calculator computes comprehensive margin requirements for derivatives portfolios, including:

- **Total Margin** = SPAN Margin + Exposure Margin
- **SPAN Margin** = Scanning Risk + Calendar Spread - Net Option Value
- **Exposure Margin** = Notional Value × ELM Rate
- **Premium Receivable** = Short Option Premium × Net Quantity
- **Margin Benefit** = Total Individual Margin − Total Combined Margin

## Input Files Used

- **SPAN File**:  
  - Format: `nscll.yyyymmdd.spn`  
  - Description: Contains all instrument and risk parameter details required for margin calculation.

- **Exposure Limit Charge Rate File**:  
  - Format: `ael.ddmmyyyy.csv`  
  - Description: Provides the applicable Exposure Limit Margin (ELM) rates for stock derivatives. The file specifies rates for both OTM (Out of the Money) and OTH (Other) categories, and the calculator applies the relevant charge based on the date and instrument.

## Core Components

### 1. Scanning Risk (SPAN Risk Array)

The scanning risk represents the worst-case scenario loss calculated from 16 different market scenarios.

**Methodology:**
- **Risk Array**: Each instrument has a 16-element array representing potential gains/losses under different market conditions based on underlying price changes and volatility changes. The risk arrays for a position is based on going long on it and getting the potential gains/losses.
- **Portfolio Aggregation**: Risk arrays from all positions in the same underlying are combined
- **Position Adjustment**: Short positions have their risk arrays inverted (multiplied by -1)
- **Scenario Calculation**: Each scenario loss = adjusted_risk_array[i] × |quantity| × conversion_factor
- **Portfolio Risk Array**: Sum of all position scenario losses for each of the 16 scenarios
- **Calculation**: `Scanning Risk = max(portfolio_risk_array)`
- **Result**: Maximum loss among all 16 scenarios (minimum 0 if no loss)

### 2. Calendar Spread Charge

Addresses the basis risk between different contract months for the same underlying.

**Calculation Process:**
1. **Delta Conversion**: Convert all positions to delta equivalents using the composite delta from span file
2. **Month Grouping**: Group positions by expiry month
3. **Spread Formation**: Match opposite deltas (long and short) across months (near to far)
4. **Charge Application**: Apply spread rate to far month notional value

**Spread Rates:**
- **Index Derivatives**: 1.75% of far month notional value
- **Stock Derivatives**: 2.2% of far month notional value

**Residual Handling:**
- Unmatched deltas carry forward to next month
- Full margin applied to final residual delta

### 3. Net Option Value (NOV)

Provides offsetting benefits for long option positions against short positions.

**Calculation:**
- **LOV (Long Option Value)**: Sum of all long option positions
- **SOV (Short Option Value)**: Sum of all short option positions
- **NOV = LOV - SOV**

**Valuation:**
- Uses real-time option prices from Redis
- Includes conversion factors for proper scaling

### 4. Exposure Margin (Extreme Loss Margin)

Protects against extreme market movements beyond normal SPAN scenarios.

**Base Rates:**
- **Index Derivatives**: 2% of notional value
- **Stock Derivatives**: 3.5% of notional value

**Special Cases:**

#### Index Options:
- **Normal Rate**: 2%
- **OTM (>10% from spot)**: 3%
- **Long Maturity (>9 months)**: 5%

#### Stock Options:
- **OTM (>30% from spot)**: Rate from AEL CSV using OTM tag
- **ITM/ATM (!>30% from spot)**: Rate from AEL CSV using OTH tag
- **Default**: 3.5%

#### Futures:
- **Index Futures**: 2% 
- **Stock Futures**: 3.5% using from AEL CSV using OTH tag

**Notional Value Calculation:**
- **Futures**: Contract value at last traded price × quantity × conversion factor
- **Options**: Underlying value × quantity × conversion factor

### 5. Premium Receivable

Credit for premiums received from short option positions.

**Calculation:**
- **Short Options Only**: Only applies to sold options
- **Premium Value**: Option price × quantity × conversion factor
- **Data**: Uses close market price from Redis

## References

- [NSE Span Methodology](https://www.nseclearing.in/risk-management/equity-derivatives/nsccl-span) - NSE Outline of SPAN
- [NSE Circular CMPT44391](https://nsearchives.nseindia.com/content/circulars/CMPT44391.pdf) - Extreme Loss Margin Rates/ Calendar Spread Rate/ File Formats
- [LSEG SPAN Methodology](https://www.lseg.com/content/dam/post-trade/clearing/risk-management/span-methodology.pdf) - Detailed Methodology Explanation
- [CME SPAN Methodology](https://www.cmegroup.com/clearing/files/span-methodology.pdf) - Official methodology

## SPAN XML File Structure

The SPAN file is an XML document containing risk parameters for all derivatives instruments.

### **File Structure Overview**

```xml
<spn>
  <!-- Futures Portfolios -->
  <futPf>
    <pfCode>...</pfCode>
    <name>...</name>
    <currency>INR</currency>
    <cvf>...</cvf>  <!-- Conversion Factor -->
    <scanRate>
      <priceScan>...</priceScan>
      <volScan>...</volScan>
    </scanRate>
    <fut>
      <p>...</p>      <!-- Current Price -->
      <pe>...</pe>    <!-- Expiry Date -->
      <ra>            <!-- Risk Array (16 scenarios) -->
        <a>...</a>
        <a>...</a>
        <!-- ... 16 total -->
      </ra>
    </fut>
  </futPf>

  <!-- Options Portfolios -->
  <oopPf>
    <pfCode>...</pfCode>
    <name>...</name>
    <currency>INR</currency>
    <cvf>...</cvf>  <!-- Conversion Factor -->
    <scanRate>
      <priceScan>...</priceScan>
      <volScan>...</volScan>
    </scanRate>
    <series>
      <pe>...</pe>    <!-- Expiry Date -->
      <opt>
        <k>...</k>    <!-- Strike Price -->
        <p>...</p>    <!-- Current Price -->
        <o>C/P</o>    <!-- Option Type (C=Call, P=Put) -->
        <d>...</d>    <!-- Delta -->
        <ra>          <!-- Risk Array (16 scenarios) -->
          <a>...</a>
          <a>...</a>
          <!-- ... 16 total -->
        </ra>
      </opt>
    </series>
  </oopPf>
</spn>
```

### **Data Extraction**

#### **Futures (`<futPf>` elements):**
- **Portfolio Level**: `name`, `currency`, `cvf` (conversion factor), scan rates
- **Contract Level**: `p` (current price), `pe` (expiry date), `ra` (risk array)
- **Instrument Code**: `{name}_FUTURE_{expiry_date}`

#### **Options (`<oopPf>` elements):**
- **Portfolio Level**: `name`, `currency`, `cvf` (conversion factor), scan rates
- **Series Level**: `pe` (expiry date)
- **Contract Level**: `k` (strike), `p` (current price), `o` (option type), `d` (delta), `ra` (risk array)
- **Instrument Code**: `{name}_{option_type}_{strike}_{expiry_date}`

### **Key Elements Extracted**

1. **Risk Arrays (`<ra>`)**: 16-element arrays representing potential gains/losses under different market scenarios
2. **Greeks**: Delta values for options (other Greeks not available in this format)
3. **Pricing**: Current market prices for all instruments
4. **Contract Details**: Strike prices, expiry dates, option types
5. **Conversion Factors**: Lot size multipliers for proper position scaling

### **Parsing Process**

1. **Futures Parsing**: Iterates through `<futPf>` elements, extracts portfolio-level data, then processes each `<fut>` contract
2. **Options Parsing**: Iterates through `<oopPf>` elements, extracts portfolio-level data, processes each `<series>` (expiry), then each `<opt>` contract
3. **Risk Array Processing**: Extracts all 16 `<a>` elements within each `<ra>` tag
4. **Instrument Creation**: Creates `Instrument` objects with all extracted data for margin calculations
 
## Project Structure & Code Scaffolding

```
parser span/
├── span_parser.py                    # Core SPAN XML file parser
├── portfolio_executor.py             # Portfolio loading and execution engine
├── margin_calculator/                # Margin calculation module
│   ├── __init__.py                   # Module exports
│   ├── margin_calculator.py          # Main margin calculation engine
│   ├── elm_margin_calculator.py      # Exposure Limit Margin calculator
│   └── redis_price_manager.py        # Redis price data manager
├── span_files/                       # Input data files
│   ├── nsccl.20250820.i01.spn        # NSE SPAN XML file example
│   └── ael_20082025.csv              # Exposure Limit Margin rates example
├── sample_portfolio .csv             # Sample portfolio data/ Input data csv
├── requirements.txt                  # Python dependencies
└── README.md                         # Project documentation
```

### Core Components Architecture

#### 1. **SPAN Parser** (`span_parser.py`)
```python
@dataclass
class Instrument:
    """Financial instrument with SPAN risk parameters"""
    code: str                    # Unique instrument identifier
    name: str                    # Underlying symbol (e.g., NIFTY, BANKNIFTY)
    instrument_type: str         # Future, Call, Put
    currency: str               # Currency (INR)
    current_price: float        # Market price from SPAN file
    conversion_factor: float = 1.0  # Lot size multiplier
    strike_price: Optional[float] = None  # Strike price for options
    expiry_date: Optional[str] = None     # Expiry date (YYYYMMDD)
    delta: Optional[float] = None         # Option delta
    price_scan_rate: float = 0.0          # Price scan rate
    volatility_scan_rate: float = 0.0     # Volatility scan rate
    risk_array: Optional[List[float]] = None  # 16-element SPAN risk array

class SPANParser:
    """Parses NSE SPAN XML files and extracts instrument data"""
    def __init__(self, file_path: str):
        """Initialize parser with SPAN file path"""
    
    def parse(self) -> Dict[str, Instrument]:
        """Main parsing method - extracts all instrument data from SPAN file"""
    
    def _parse_futures(self, root):
        """Parse futures instruments from <futPf> elements"""
    
    def _parse_option_portfolios(self, root):
        """Parse option portfolios from <oopPf> elements"""
```

#### 2. **Margin Calculator Module** (`margin_calculator/`)

**Main Calculator** (`margin_calculator.py`):
```python
@dataclass
class Position:
    """Trading position in a portfolio"""
    instrument_code: str
    quantity: int  # Positive for long, negative for short

@dataclass
class PortfolioMarginResult:
    """Comprehensive margin calculation result"""
    span_risk_requirement: float
    calendar_spread_charge: float
    total_span_margin: float
    exposure_margin: float
    net_option_value: float
    premium_receivable: float
    total_margin: float
    group_details: Dict[str, Any]

class MarginCalculator:
    """Main engine for SPAN margin calculations"""
    def __init__(self, span_parser: SPANParser, redis_manager: RedisPriceManager, elm_file_path: str):
        """Initialize with SPAN parser, Redis manager, and ELM file path"""
    
    def calculate_portfolio_margin(self, positions: List[Position]) -> PortfolioMarginResult:
        """Calculate comprehensive margin for entire portfolio grouped by underlying"""
    
    def calculate_span_risk_requirement(self, positions: List[Position]) -> float:
        """Calculate scanning risk from 16 SPAN scenarios for positions in same underlying"""
    
    def calculate_calendar_spread_charge(self, positions: List[Position]) -> float:
        """Calculate calendar spread charge for basis risk between contract months"""
    
    def calculate_net_option_value(self, positions: List[Position]) -> float:
        """Calculate Net Option Value (LOV - SOV) for option positions"""
    
    def calculate_premium_receivable(self, positions: List[Position]) -> float:
        """Calculate premium receivable for short option positions"""
    
    def calculate_individual_margin(self, position: Position) -> Dict[str, float]:
        """Calculate margin requirements for a single position"""
    
    def get_notional_value(self, positions: List[Position], underlying_prices: Dict[str, float] = None) -> float:
        """Calculate total notional value of positions"""
```

**ELM Calculator** (`elm_margin_calculator.py`):
```python
class ELMMarginCalculator:
    """Handles Exposure Limit Margin calculations using AEL CSV rates"""
    def __init__(self, elm_file_path: str, span_parser: SPANParser, redis_manager: RedisPriceManager, margin_calculator=None):
        """Initialize with ELM file path, SPAN parser, Redis manager"""
    
    def _load_elm_rates(self, elm_file_path: str) -> Dict[str, Dict[str, float]]:
        """Load ELM rates from CSV file"""
    
    def get_elm_rate(self, instrument: Instrument, quantity: int, underlying_price: float = None) -> float:
        """Get appropriate ELM rate based on instrument type and OTM status"""
    
    def calculate_total_exposure_margin(self, positions: List[Position]) -> float:
        """Calculate total exposure margin for all positions"""
```

**Redis Price Manager** (`redis_price_manager.py`):
```python
class RedisPriceManager:
    """Manages Redis connections and real-time price data"""
    def __init__(self, host: str = '127.0.0.1', port: int = 6379, db: int = 0):
        """Initialize Redis connection"""
    
    def get_option_price_for_instrument(self, instrument: Instrument) -> Optional[float]:
        """Get option price from Redis using market:latest:{UNDERLYING}{YY}{MMM}{STRIKE}{CE|PE} format"""
    
    def get_underlying_spot_price(self, underlying_name: str) -> Optional[float]:
        """Get underlying spot price from Redis using market:latest:{UNDERLYING} format"""
```

#### 3. **Portfolio Executor** (`portfolio_executor.py`)
```python
def load_portfolio_from_detailed_csv(file_path: str, instruments: Dict[str, object]) -> List[Position]:
    """Load portfolio from CSV with validation against available instruments"""
    # Supports CSV format: product_type, symbol, expiry, net_qty, option_type, strike, buy/sell
    # Validates instrument existence and shows available expiries/strikes if not found

def display_margin_results(results: PortfolioMarginResult, individual_margins: Dict, positions: List[Position], instruments: Dict):
    """Display comprehensive margin calculation results in tabular format"""

def main():
    """Main execution flow"""
    # 1. Parse SPAN file
    # 2. Connect to Redis
    # 3. Initialize margin calculator
    # 4. Load portfolio from CSV
    # 5. Calculate individual and portfolio margins
    # 6. Display results
```

## How to Use the SPAN Margin Calculator

### Prerequisites

1. **Redis Server**:  
   - A running Redis instance is required for real-time price data.  
   - **Connection**: Use SSH port forwarding to connect securely:  
     ```bash
     ssh -N -L 6379:localhost:6379 anurag@bullerocapital.com
     ```
2. **NSE Data Files**:  
   - Download the latest SPAN XML file and AEL (Exposure Limit Margin) CSV file from the [NSE Clearing website](https://www.nseindia.com/all-reports-derivatives).
3. **Python Environment**:  
   - Ensure Python and dependencies are installed.  
   - Install requirements with:  
     ```bash
     pip install -r requirements.txt
     ```
     For now the only requirement is Redis.

### Prepare Input Data Files

#### A. SPAN XML File
- **Source**: [NSE Clearing](https://www.nseindia.com/all-reports-derivatives)
- **Format**: `nsccl.yyyymmdd.filenumber.spn` (e.g., `nsccl.20250820.i01.spn`)
- **Location**: Place in the `span_files/` directory.
- **Description**: Contains risk parameters for all derivatives instruments.

#### B. AEL (Exposure Limit Margin) CSV File
- **Source**: [NSE Clearing](https://www.nseindia.com/all-reports-derivatives)
- **Format**: `ael_ddmmyyyy.csv` (e.g., `ael_20082025.csv`)
- **Location**: Place in the `span_files/` directory.
- **Description**: Contains ELM rates for stock derivatives.

#### C. Portfolio CSV File
- **Format Example**:
  ```csv
  product_type,symbol,expiry,net_qty,option_type,strike,buy/sell
  Option,ANGELONE,28-Aug-25,-500,Put,2500,sell
  Future,ANGELONE,28-Aug-25,500,,,buy
  Option,NIFTY,29-Aug-25,100,Call,19500,buy
  ```
- **Column Details**:
  - `product_type`: `Option` or `Future`
  - `symbol`: Underlying symbol (e.g., `NIFTY`, `BANKNIFTY`, `ANGELONE`)
  - `expiry`: Expiry date in `DD-MMM-YY` format (e.g., `28-Aug-25`)
  - `net_qty`: Position quantity (positive for long, negative for short)
  - `option_type`: `Call` or `Put` (only for options)
  - `strike`: Strike price (only for options)
  - `buy/sell`: `buy` or `sell` (optional; `net_qty` sign takes precedence)

### Configure Redis Connection

- In `portfolio_executor.py`, update the following variables in the `main()` function as needed:
  ```python
  REDIS_HOST = "127.0.0.1"  # Your Redis host (use localhost if using SSH tunnel)
  REDIS_PORT = 6379         # Your Redis port
  ```
- **Redis Data Format Used**:
  - **Options**:  
    `market:latest:{UNDERLYING}{YY}{MMM}{STRIKE}{CE|PE}`  
    Example: `market:latest:NIFTY25AUG19500CE`
  - **Underlying Spot**:  
    `market:latest:{UNDERLYING}`  
    Example: `market:latest:NIFTY50` (for NIFTY)

### Update File Paths

- In `portfolio_executor.py`, set the file paths in the `main()` function:
  ```python
  SPAN_FILE_PATH = "span_files/nsccl.20250820.i01.spn"  # Your SPAN file
  ELM_FILE_PATH = "span_files/ael_20082025.csv"         # Your AEL file
  DETAILED_PORTFOLIO_FILE_PATH = "your_portfolio.csv"   # Your portfolio file
  ```

### Run the Margin Calculator

- Execute the main program:
  ```bash
  python portfolio_executor.py
  ```
### Output Format

The program will display:

1. **Individual Position Margins**: Each position's SPAN and exposure margin.
2. **Portfolio Summary**: Combined margin requirements by underlying.
3. **Final Results**: Total margin, premium receivable, and margin benefit.
