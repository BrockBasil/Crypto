#!/usr/bin/env python3
"""
Script for a cryptocurrency trading bot that renders a GUI built from the Kivy framework when ran.

Attributes
----------
symbol : str
	Symbol associated with the base currency of a trading pair.
altSymbol : str
	Alternative symbol associated with the base currency of a trading pair.
market : str
	Symbol associated with the quote currency of a trading pair.
altMarket : str
	Alternative symbol associated with the quote currency of a trading pair.
timeSlice : int
	Time span in minutes for each data point. Must be 1, 5, 15, or 60.
stopLossPortion : float
	Percentage of current price to set stop loss limit as decimal. Must be between 0.0 and 1.0.

Classes
-------
Bot(BoxLayout)
	Contains methods to implement trading strategy and update app with current data.
MainApp(MDApp)
	Constructs the layout and functionality of the application window. 
"""

# Kivy library imports
from kivy.lang import Builder
from kivymd.app import MDApp
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.properties import StringProperty
from kivy.properties import ObjectProperty
from kivy.properties import NumericProperty
from kivy.properties import BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg

# Library imports
import requests
import threading
import time
import matplotlib.pyplot as plt
import pandas as pd
from configparser import ConfigParser
from colorama import Fore
from colorama import Back
from colorama import Style
from datetime import datetime

# File imports
from Contact import *
from HelperFuncs import *
from IndicatorFuncs import *
from KrakenFuncs import *

fig, (ax1, ax2) = plt.subplots(2, gridspec_kw={"height_ratios": [2, 1]})
fig.tight_layout()
fig.subplots_adjust(left=0.027)
Window.size = (1000, 700)

# global variables initial parameters
config = ConfigParser()
config.read("config.ini")

symbol = config["settings"]["symbol"]
altSymbol = config["settings"]["altSymbol"]
market = config["settings"]["market"]
altMarket = config["settings"]["altMarket"]
timeSlice = int(config["settings"]["timeSlice"])
stopLossPortion = float(config["settings"]["stopLossPortion"])


class Bot(BoxLayout):
	"""
	Contains methods to implement trading strategy and update app with current data.

	Methods
	-------
	__init__(self, **kwargs)
		Initializes graphbox wideget.
	run_strategy_rsi_bb(self, rates)
		Implements a RSI, BB, StopLoss strategy.
	analyze_rsi_bb(self, rates)
		Analyzes most recent market data and updates bot settings with most efficient 
		variable combination.
	update_variables(self, rates)
		Updates displayed variables and plots with newest data.
	add_bb_plot(self, ratesHl2)
		Adds BB data to subplot ax1.
	add_cadles_plot(self, rates)
		Adds open, high, low, close data to subplot ax1.
	add_rsi_plot(self, ratesHl2)
		Adds RSI data to subplot ax2.
	"""

	# sets properties with initial values
	analyzeTime = StringProperty("00")
	inSellPeriod = BooleanProperty(False)
	inBuyPeriod = BooleanProperty(False)

	rsiPeriodLength = NumericProperty(6)
	rsiUpperBound = NumericProperty(70.0)
	rsiLowerBound = NumericProperty(30.0)
	bbPeriodLength = NumericProperty(34)
	bbLevel = NumericProperty(2.75)

	# Sets stopLoss limits.
	rates = get_historic_rates(symbol, timeSlice)
	if float(kraken_get_balance(altMarket)) > (float(kraken_get_balance(altSymbol)) * rates["Close"].iloc[-1]):
		stopLossUpper = rates["High"].iloc[-1] * (1.0 + (2 * stopLossPortion))
		stopLossLower = 0.0
	else:
		stopLossLower = rates["Low"].iloc[-1] * (1.0 - (2 * stopLossPortion))
		stopLossUpper = 0.0


	def __init__(self, **kwargs):
		"""
		Initializes graphbox wideget.
		"""

		super().__init__(**kwargs)

		# Adds graph box
		self.graphBox = self.ids.graphBox
		self.graphBox.add_widget(FigureCanvasKivyAgg(plt.gcf()))


	def run_strategy_rsi_bb(self, rates):
		"""
		Implements a relative-strength-index, bollinger-bands, stop-loss strategy.

		Parameters
		----------
		rates : pandas.DataFrame
			Rates of a cryptocurrency in chronological order.
		"""

		try:
			# Get rates, high/low average, rsi values and bb bands
			#ratesHl2 = pd.Series((rates["High"] + rates["Low"]).div(2).values, index=rates.index)
			ratesHl2 = rates["Close"]
			ratesRsi = get_rsi(ratesHl2, self.rsiPeriodLength)
			(bbUpper, bbMiddle, bbLower) = get_bb(ratesHl2, self.bbPeriodLength, self.bbLevel)

			# Determines sell, buy, or hold action for bot
			if not self.inSellPeriod:
				if (ratesRsi.iloc[-2] > self.rsiUpperBound) and (rates["High"].iloc[-2] > bbUpper.iloc[-2]):
					send_msg("Sell signal triggered")
					print(Fore.GREEN + "Sell signal" + Style.RESET_ALL)
					self.inSellPeriod = True
			else:
				if (ratesRsi.iloc[-1] <= (self.rsiUpperBound - 3)) and (rates["High"].iloc[-1] <= bbUpper.iloc[-1]):
					if self.stopLossUpper == 0.0:
						create_order(rates["Close"].iloc[-1], "sell", altSymbol, altMarket, market)
						self.stopLossUpper = rates["High"].iloc[-1] * (1.0 + stopLossPortion)
					else:
						print(Fore.RED + "***double-sell***" + Style.RESET_ALL)
					self.inSellPeriod = False
					self.stopLossLower = 0.0
					
			if not self.inBuyPeriod:
				if (ratesRsi.iloc[-2] < self.rsiLowerBound) and (rates["Low"].iloc[-2] < bbLower.iloc[-2]):
					send_msg("Buy signal triggered")
					print(Fore.GREEN + "Buy signal" + Style.RESET_ALL)
					self.inBuyPeriod = True
			else:
				if (ratesRsi.iloc[-1] >= (self.rsiLowerBound + 3)) and (rates["Low"].iloc[-1] >= bbLower.iloc[-1]):
					if self.stopLossLower == 0.0:
						create_order(rates["Close"].iloc[-1], "buy", altSymbol, altMarket, market)
						self.stopLossLower = rates["Low"].iloc[-1] * (1.0 - stopLossPortion)
					else:
						print(Fore.RED + "***double-buy***" + Style.RESET_ALL)
					self.inBuyPeriod = False
					self.stopLossUpper = 0.0

			if self.stopLossLower > 0.0:
				if (rates["Low"].iloc[-2] * (1.0 - stopLossPortion)) > self.stopLossLower:
					self.stopLossLower = rates["Low"].iloc[-2] * (1.0 - stopLossPortion)
				if rates["Low"].iloc[-1] < self.stopLossLower:
					create_order(rates["Close"].iloc[-1], "sell", altSymbol, altMarket, market)
					self.stopLossUpper = rates["High"].iloc[-1] * (1.0 + stopLossPortion)
					self.stopLossLower = 0.0

			if self.stopLossUpper > 0.0:
				if (rates["High"].iloc[-2] * (1.0 + stopLossPortion)) < self.stopLossUpper:
					self.stopLossUpper = rates["High"].iloc[-2] * (1.0 + stopLossPortion)
				if rates["High"].iloc[-1] > self.stopLossUpper:
					create_order(rates["Close"].iloc[-1], "buy", altSymbol, altMarket, market)
					self.stopLossLower = rates["Low"].iloc[-1] * (1.0 - stopLossPortion)
					self.stopLossUpper = 0.0

		# Catches error in Strategy thread and prints to screen
		except Exception as err:
			send_msg("STRATEGY-ERROR\nCheck to see if bot is functioning")
			print(Fore.RED + "STRATEGY-ERROR." + Style.RESET_ALL)
			print(err)


	def analyze_rsi_bb(self, rates):
		"""
		Analyzes most recent market data and updates bot settings with most efficient 
		variable combination.

		Parameters
		----------
		rates : pandas.DataFrame
			Rates of a cryptocurrency in chronological order.
		"""

		try:
			print("Analyze thread started")
			# Variable holders
			bestDelta = 0.0
			portion = 0.99

			stopLossLower = 0.0
			stopLossUpper = 0.0
			thisInSellPeriod = False
			thisInBuyPeriod = False

			currentTopParameters = []
			topParameters = []

			#ratesHl2Series = pd.Series((rates["High"] + rates["Low"]).div(2).values, index=rates.index)
			ratesHl2Series = rates["Close"]
			
			for thisRsiPeriodLength in range(4, 13):
				# Set RSI values
				ratesRsiSeries = get_rsi(ratesHl2Series, thisRsiPeriodLength)

				for thisRsiUpperBound in range(80, 66, -2):
					for thisRsiLowerBound in range(20, 34, 2):
						for thisBbPeriodLength in range(thisRsiPeriodLength, 36, 2):
							# Convert Pandas series to lists
							ratesHigh = rates["High"].tolist()[(thisBbPeriodLength - 1):]
							ratesLow = rates["Low"].tolist()[(thisBbPeriodLength - 1):]
							ratesHl2 = ratesHl2Series.tolist()[(thisBbPeriodLength - 1):]
							ratesRsi = ratesRsiSeries.tolist()[(thisBbPeriodLength - thisRsiPeriodLength):]
							dates = rates.index.tolist()[(thisBbPeriodLength - 1):]
					
							for bbLevelDouble in range(6, 12):
								usdStart = 100.0
								cryptoStart = 100.0 / ratesHl2[0]
								usdEnd = usdStart
								cryptoEnd = cryptoStart

								# Set BB values
								thisBbLevel = float(bbLevelDouble) / 4.0
								(bbUpperSeries, bbMiddleSeries, bbLowerSeries) = get_bb(ratesHl2Series, thisBbPeriodLength, thisBbLevel)

								# Convert Pandas series to lists
								bbUpper = bbUpperSeries.tolist()[(thisBbPeriodLength - 1):]
								bbMiddle = bbMiddleSeries.tolist()[(thisBbPeriodLength - 1):]
								bbLower = bbLowerSeries.tolist()[(thisBbPeriodLength - 1):]
								stopLossLower = 0.0
								stopLossUpper = 0.0

								# Parse through data, determines buy or sell times and prices, and calculates endWallet
								for i in range(len(dates)):
									if not thisInSellPeriod:
										if (ratesRsi[i] > thisRsiUpperBound) and (ratesHigh[i] > bbUpper[i]):
											thisInSellPeriod = True
									else:
										if (ratesRsi[i] <= (thisRsiUpperBound - 3)) and (ratesHigh[i] <= bbUpper[i]):
											usdEnd = usdEnd + (cryptoEnd * ratesHl2[i] * .995 * portion)
											cryptoEnd = cryptoEnd * (1.0 - portion)
											if stopLossUpper == 0.0:
												stopLossUpper = ratesHigh[i] * (1.0 + stopLossPortion)
											stopLossLower = 0.0
											thisInSellPeriod = False

									if not thisInBuyPeriod:
										if (ratesRsi[i] < thisRsiLowerBound) and (ratesLow[i] < bbLower[i]):
											thisInBuyPeriod = True
									else:
										if (ratesRsi[i] >= (thisRsiLowerBound + 3)) and (ratesLow[i] >= bbLower[i]):
											cryptoEnd = cryptoEnd + (usdEnd * .995 * portion / ratesHl2[i])
											usdEnd = usdEnd * (1.0 - portion)
											if stopLossLower == 0.0:
												stopLossLower = ratesLow[i] * (1.0 - stopLossPortion)
											stopLossUpper = 0.0
											thisInBuyPeriod = False

									if stopLossLower > 0.0:
										if (ratesLow[i] * (1.0 - stopLossPortion)) > stopLossLower:
											stopLossLower = ratesLow[i] * (1.0 - stopLossPortion)
										if ratesLow[i] < stopLossLower:
											usdEnd = usdEnd + (cryptoEnd * ratesHl2[i] * .995 * portion)
											cryptoEnd = cryptoEnd * (1.0 - portion)
											stopLossUpper = ratesHigh[i] * (1.0 + stopLossPortion)
											stopLossLower = 0.0

									if stopLossUpper > 0.0:
										if (ratesHigh[i] * (1.0 + stopLossPortion)) < stopLossUpper:
											stopLossUpper = ratesHigh[i] * (1.0 + stopLossPortion)
										if ratesHigh[i] > stopLossUpper:
											cryptoEnd = cryptoEnd + (usdEnd * .995 * portion / ratesHl2[i])
											usdEnd = usdEnd * (1.0 - portion)
											stopLossLower = ratesLow[i] * (1.0 - stopLossPortion)
											stopLossUpper = 0.0

								walletStart = 200.0
								walletEnd = usdEnd + (cryptoEnd * ratesHl2[-1])

								# Calculates action and no-action gains and losses
								noActionGainLoss = (ratesHl2[-1] - ratesHl2[0]) / (2 * ratesHl2[0])
								actionGainLoss = (walletEnd - walletStart) / walletStart
								delta = actionGainLoss - noActionGainLoss

								# Append newest top parameter combination
								if (delta > 0.0) and (delta >= bestDelta):
									bestDelta = delta
									currentTopParameters.append([delta, thisRsiPeriodLength, thisRsiUpperBound, thisRsiLowerBound,
										thisBbPeriodLength, thisBbLevel, thisInSellPeriod, thisInBuyPeriod])

								# Reset variable holders
								thisInSellPeriod = False
								thisInBuyPeriod = False

				# Append top 3 parameter combinations for rsiPeriodLength
				currentTopParameters.reverse()
				if len(currentTopParameters) > 3:
					numberOfParameters = 3
				else:
					numberOfParameters = len(currentTopParameters)

				for i in range(numberOfParameters):
					topParameters.append(currentTopParameters[i])

				# Reset variable holders
				bestDelta = 0.0
				currentTopParameters = []

			# Print top parameter combinations if found
			print("{}".format(datetime.now().strftime("%m/%d - %H:%M:%S")))
			if len(topParameters) > 0:
				print("delta, rsiP, rsiU, rsiL, bbP, bbLvl, sellAcPer, BuyActPer")
				topParameters.sort()
				for parameters in topParameters:
					print(parameters)

				# Updates parameters with new values
				self.rsiPeriodLength = topParameters[-1][1]
				self.rsiUpperBound = topParameters[-1][2]
				self.rsiLowerBound = topParameters[-1][3]
				self.bbPeriodLength = topParameters[-1][4]
				self.bbLevel = topParameters[-1][5]
				if self.inSellPeriod == False:
					self.inSellPeriod = topParameters[-1][6]
				if self.inBuyPeriod == False:
					self.inBuyPeriod = topParameters[-1][7]

				print("Parameters updated to:")
				print(topParameters[-1])

			else:
				print(Fore.RED +
					"No adequate parameters found. Reattempting analysis next cycle." +
					Style.RESET_ALL)

		# Catches error in Analyze thread and prints to screen
		except Exception as err:
			send_msg("ANALYZE-ERROR\nCheck to see if bot is functioning")
			print(Fore.RED + "ANALYZE-ERROR." + Style.RESET_ALL)
			print(err)


	def update_variables(self, rates):
		"""
		Updates displayed variables and plots with newest data.

		Parameters
		----------
		rates : pandas.DataFrame
			Rates of a cryptocurrency in chronological order.
		"""

		#ratesHl2 = pd.Series((rates["High"] + rates["Low"]).div(2).values, index=rates.index)
		ratesHl2 = rates["Close"]
		ratesRsi = get_rsi(ratesHl2, self.rsiPeriodLength)
		(bbUpper, bbMiddle, bbLower) = get_bb(ratesHl2, self.bbPeriodLength, self.bbLevel)

		self.ids.open_var.text = (str(rates["Open"].iloc[-1]))[:7]
		self.ids.high_var.text = (str(rates["High"].iloc[-1]))[:7]
		self.ids.low_var.text = (str(rates["Low"].iloc[-1]))[:7]
		self.ids.close_var.text = (str(rates["Close"].iloc[-1]))[:7]

		self.ids.bb_upper_var.text = (str(bbUpper.iloc[-1]))[:7]
		self.ids.bb_lower_var.text = (str(bbLower.iloc[-1]))[:7]
		self.ids.bb_level_var.text = (str(self.bbLevel))
		self.ids.bb_period_var.text = (str(self.bbPeriodLength))

		self.ids.rsi_var.text = (str(ratesRsi.iloc[-1]))[:5]
		self.ids.rsi_upper_var.text = (str(self.rsiUpperBound))[:5]
		self.ids.rsi_lower_var.text = (str(self.rsiLowerBound))[:5]
		self.ids.rsi_period_var.text = (str(self.rsiPeriodLength))

		self.ids.stoploss_upper_var.text = (str(self.stopLossUpper))[:7]
		self.ids.stoploss_lower_var.text = (str(self.stopLossLower))[:7]

		# Clear plot and widget, set new plot and widget
		plt.cla()
		ax1.cla()
		ax2.cla()
		self.graphBox.clear_widgets()
		Bot.add_bb_plot(self, ratesHl2)
		Bot.add_cadles_plot(self, rates)
		Bot.add_rsi_plot(self, ratesHl2)
		self.graphBox.add_widget(FigureCanvasKivyAgg(plt.gcf()))


	def add_bb_plot(self, ratesHl2):
		"""
		Adds BB data to subplot ax1.
		
		Parameters
		----------
		ratesHl2 : pandas.Series
			Rates of a cryptocurrency in chronological order.
		"""

		size = 150 - self.bbPeriodLength + 1
		(bbUpper, bbMiddle, bbLower) = get_bb(ratesHl2, self.bbPeriodLength, self.bbLevel)
		ax1.plot(bbUpper.tail(size), label="Bollinger Up", linewidth=1, c="b")
		ax1.plot(bbMiddle.tail(size), label="Bollinger Middle", linewidth=1, c="black")
		ax1.plot(bbLower.tail(size), label="Bollinger Down", linewidth=1, c="b")
		ax1.set_xticks([0,
			int(size / 10) - 1,
			int(size * 2 / 10) - 1,
			int(size * 3 / 10) - 1,
			int(size * 4 / 10) - 1,
			int(size * 5 / 10) - 1,
			int(size * 6 / 10) - 1,
			int(size * 7 / 10) - 1,
			int(size * 8 / 10) - 1,
			int(size * 9 / 10) - 1,
			size - 1])
		ax1.tick_params(labelsize=5)
		ax1.yaxis.tick_right()
		plt.setp(ax1.xaxis.get_majorticklabels(), rotation=40, ha="right")
		ax1.grid()


	def add_cadles_plot(self, rates):
		"""
		Adds open, high, low, close data to subplot ax1.

		Parameters
		----------
		rates : pandas.DataFrame
			Rates of a cryptocurrency in chronological order.
		"""

		size = 150 - self.bbPeriodLength + 1
		rates = rates.tail(size)
		down = rates[rates.Close < rates.Open]
		up = rates[rates.Close >= rates.Open]
		widthOC = 0.8
		widthHL = 0.2

		ax1.bar(up.index, up.Close - up.Open, widthOC, bottom=up.Open, color="green")
		ax1.bar(up.index, up.High - up.Close, widthHL, bottom=up.Close, color="green")
		ax1.bar(up.index, up.Low - up.Open, widthHL, bottom=up.Open, color="green")
		ax1.bar(down.index, down.Close - down.Open, widthOC, bottom=down.Open, color="red")
		ax1.bar(down.index, down.High - down.Open, widthHL, bottom=down.Open, color="red")
		ax1.bar(down.index, down.Low - down.Close, widthHL, bottom=down.Close, color="red")


	def add_rsi_plot(self, ratesHl2):
		"""
		Adds RSI data to subplot ax2.
		
		Parameters
		----------
		ratesHl2 : pandas.Series
			Rates of a cryptocurrency in chronological order.
		"""

		size = 150 - self.bbPeriodLength + 1
		rsi = get_rsi(ratesHl2, self.rsiPeriodLength)
		ax2.plot(rsi.tail(size), label="RSI", c="black", linewidth=1)
		ax2.axhline(y=self.rsiUpperBound, color='black', linestyle='--', linewidth=2)
		ax2.axhline(y=self.rsiLowerBound, color='black', linestyle='--', linewidth=2)
		ax2.fill_between(ratesHl2.tail(size).index, self.rsiUpperBound, rsi.tail(size),
				where=(rsi.tail(size) > self.rsiUpperBound),
				label="Overbought",
				interpolate=True, color="red", alpha=0.5)
		ax2.fill_between(ratesHl2.tail(size).index, self.rsiLowerBound, rsi.tail(size),
				where=(rsi.tail(size) < self.rsiLowerBound),
				label="Oversold",
				interpolate=True, color="green", alpha=0.5)
		ax2.set_xticks([0,
			int(size / 10) - 1,
			int(size * 2 / 10) - 1,
			int(size * 3 / 10) - 1,
			int(size * 4 / 10) - 1,
			int(size * 5 / 10) - 1,
			int(size * 6 / 10) - 1,
			int(size * 7 / 10) - 1,
			int(size * 8 / 10) - 1,
			int(size * 9 / 10) - 1,
			size - 1])
		ax2.tick_params(labelsize=5)
		ax2.yaxis.tick_right()
		plt.setp(ax2.xaxis.get_majorticklabels(), rotation=40, ha="right")
		ax2.grid()
		ax2.legend(fontsize=5)


class MainApp(MDApp):
	"""
	Contains methods to implement trading strategy and update app with current data.

	Methods
	-------
	def build(self)
		Sets the Kicy clock interval and loads the layout from Bot.kv file.
	def on_start(self, **kwargs)
		Sets initial Bot parameters.
	update_screen(self)
		Runs strategy and updates screen with most recent data.
	"""

	def build(self):
		"""
		Sets the Kicy clock interval and loads the layout from Bot.kv file.
		"""

		Clock.schedule_interval(lambda dt: self.update_screen(), 10)
		self.theme_cls.theme_style = "Dark"
		self.theme_cls.primary_palette = "BlueGray"
		Builder.load_file("Bot.kv")
		return Bot()


	def on_start(self, **kwargs):
		"""
		Sets initial Bot parameters.
		"""

		rates = get_historic_rates(symbol, timeSlice).tail(250)

		if timeSlice <= 5:
			self.analyzeTime = ((int(time.strftime("%-M")) // 20) * 20) + 20
			if self.analyzeTime == 60:
				self.analyzeTime = self.analyzeTime - 60
		elif timeSlice == 15:
			self.analyzeTime = time.strftime("%H")
		else:
			if int(time.strftime("%H")) < 6:
				self.analyzeTime = 6
			elif int(time.strftime("%H")) < 12:
				self.analyzeTime = 12
			elif int(time.strftime("%H")) < 18:
				self.analyzeTime = 18
			else:
				self.analyzeTime = 0
		print("Analyze at hour {}".format(self.analyzeTime))

		self.root.ids.symbol_pair_var.text = symbol + "-" + market
		self.root.run_strategy_rsi_bb(rates)
		self.root.update_variables(rates)


	def update_screen(self):
		"""
		Runs strategy and updates screen with most recent data.
		"""

		try:
			rates = get_historic_rates(symbol, timeSlice).tail(250)
			self.root.run_strategy_rsi_bb(rates)
			self.root.update_variables(rates)

			# ANALYZE THREAD
			if timeSlice <= 5:
				if int(time.strftime("%-M")) == self.analyzeTime:
					self.analyzeTime += 20
					if self.analyzeTime >= 60:
						self.analyzeTime = self.analyzeTime - 60
					analyzeThread = threading.Thread(target=self.root.analyze_rsi_bb, args=(rates,), daemon=True)
					analyzeThread.start()

			elif timeSlice == 15:	
				if time.strftime("%H") != self.analyzeTime:
					self.analyzeTime = time.strftime("%H")
					analyzeThread = threading.Thread(target=self.root.analyze_rsi_bb, args=(rates,), daemon=True)
					analyzeThread.start()

			else:
				if int(time.strftime("%H")) == self.analyzeTime:
					if self.analyzeTime == 18:
						self.analyzeTime = 0;
					else:
						self.analyzeTime += 6
					analyzeThread = threading.Thread(target=self.root.analyze_rsi_bb, args=(rates,), daemon=True)
					analyzeThread.start()


		except Exception as err:
			send_msg("UPDATE-SCREEN-ERROR\nCheck to see if bot is functioning")
			print(Fore.RED + "UPDATE-SCREEN-ERROR." + Style.RESET_ALL + "\n")
			print(err)


if __name__ == "__main__":
	MainApp().run()
