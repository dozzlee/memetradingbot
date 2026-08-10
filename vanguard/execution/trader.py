"""Buy/sell execution against the bot's own wallet, sized by the fixed
USD rules in vanguard/config/settings.py (POSITION_SIZE_USD, SLIPPAGE_BPS).
Every call here produces a real on-chain swap — there is no dry-run mode."""
import asyncio

from vanguard.config import settings
from vanguard.wallet import jupiter, keystore, pricing

SOL_MINT = pricing.SOL_MINT

# Kept unswapped as a buffer for network/priority fees and token-account
# rent — a $5 swap that leaves zero SOL behind can't pay for its own exit.
FEE_RESERVE_SOL = 0.01


class TradeError(RuntimeError):
    pass


async def execute_buy(mint: str) -> dict:
    keypair = keystore.load_keypair()
    address = str(keypair.pubkey())

    sol_price = await asyncio.to_thread(pricing.get_sol_price_usd)
    sol_amount = settings.POSITION_SIZE_USD / sol_price

    balance = await asyncio.to_thread(keystore.get_sol_balance, address)
    if balance < sol_amount + FEE_RESERVE_SOL:
        raise TradeError(
            f"insufficient balance: wallet has {balance:.4f} SOL, need "
            f"~{sol_amount + FEE_RESERVE_SOL:.4f} SOL (${settings.POSITION_SIZE_USD} position + fee reserve)"
        )

    lamports = int(sol_amount * 1_000_000_000)
    signature, _ = await jupiter.swap_async(SOL_MINT, mint, lamports, keypair)

    # Read the actual fill off-chain rather than trusting the quote's
    # estimate — slippage/price-impact means the real amount can differ.
    token_amount, decimals = await asyncio.to_thread(keystore.get_token_balance, address, mint)
    if not token_amount:
        raise TradeError(f"swap {signature} confirmed but no {mint} balance found afterward")

    entry_price_usd = settings.POSITION_SIZE_USD / token_amount
    return {
        "tx_sig": signature,
        "token_amount": token_amount,
        "decimals": decimals,
        "entry_price_usd": entry_price_usd,
        "size_usd": settings.POSITION_SIZE_USD,
    }


async def execute_sell(mint: str, token_amount: float, decimals: int) -> dict:
    keypair = keystore.load_keypair()
    raw_amount = int(token_amount * (10 ** decimals))
    signature, out_lamports = await jupiter.swap_async(mint, SOL_MINT, raw_amount, keypair)

    sol_out = out_lamports / 1_000_000_000
    sol_price = await asyncio.to_thread(pricing.get_sol_price_usd)
    usd_out = sol_out * sol_price
    exit_price_usd = usd_out / token_amount if token_amount else 0

    return {
        "tx_sig": signature,
        "sol_out": sol_out,
        "usd_out": usd_out,
        "exit_price_usd": exit_price_usd,
    }
