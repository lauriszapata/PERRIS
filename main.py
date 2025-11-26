from config import Config
from modules.logger import logger
from modules.state_handler import StateHandler
from modules.binance_client import BinanceClient
from modules.execution.order_executor import OrderExecutor
from modules.execution.bot_logic import BotLogic

def main():
    try:
        # Validate Config
        Config.validate()
        
        # Initialize Components
        logger.info("===================================================")
        logger.info("🚀 STARTING SNIPER BOT (High Reward 3x Version) 🚀")
        logger.info("   • Strategy: Fixed TP 2.5% / SL 3.0%")
        logger.info("   • Leverage: 3x")
        logger.info("===================================================")
        logger.info("Initializing components...")
        state_handler = StateHandler()
        client = BinanceClient()
        order_executor = OrderExecutor(client)
        
        bot = BotLogic(client, state_handler, order_executor)
        
        # Run Bot
        bot.run()
        
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        exit(1)

if __name__ == "__main__":
    main()
