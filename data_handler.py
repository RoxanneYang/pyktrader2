import datetime
import numpy as np
import pandas as pd
import scipy.stats as stats

def ohlcsum(df):
    return pd.Series([df.index[0], df['open'][0], df['high'].max(), df['low'].min(), df['close'][-1], df['volume'].sum()],
                  index = ['datetime', 'open','high','low','close','volume'])

def min_freq_group(mdf, freq = 5, index_col = 'datetime'):
    if index_col == None:
        mdf = mdf.set_index('datetime')
    min_cnt = (mdf['min_id']/100).astype(int)*60 + (mdf['min_id'] % 100)
    mdf['min_idx'] = (min_cnt/freq).astype(int)
    mdf['date_idx'] = mdf.index.date
    xdf = mdf.groupby([mdf['date_idx'], mdf['min_idx']]).apply(ohlcsum).reset_index()
    if index_col != None:
        xdf = xdf.set_index('datetime')
    return xdf

def day_split(mdf, minlist = [1500], index_col = 'datetime'):
    if index_col == None:
        mdf = mdf.set_index('datetime')
    mdf['min_idx'] = 0
    for idx, mid in enumerate(minlist):
        mdf.loc[mdf['min_id']>=mid, 'min_idx'] = idx + 1
    mdf['date_idx'] = mdf.index.date
    xdf = mdf.groupby([mdf['date_idx'], mdf['min_idx']]).apply(ohlcsum).reset_index()
    if index_col != None:
        xdf = xdf.set_index('datetime')
    return xdf

def min2daily(df):
    return pd.Series([df['open'][0], df['high'].max(), df['low'].min(), df['close'][-1], df['volume'].sum(), df['openInterest'][-1]],
                  index = ['open','high','low','close','volume', 'openInterest'])

def conv_ohlc_freq(df, freq, index_col = 'datetime'):
    if index_col == None:
        df = df.set_index('datetime')
    if freq in ['d', 'D']:
        res = df.groupby([df['date']]).apply(min2daily).reset_index().set_index(['date'])
    else:
        highcol = pd.DataFrame(df['high']).resample(freq, how ='max').dropna()
        lowcol  = pd.DataFrame(df['low']).resample(freq, how ='min').dropna()
        opencol = pd.DataFrame(df['open']).resample(freq, how ='first').dropna()
        closecol= pd.DataFrame(df['close']).resample(freq, how ='last').dropna()
        allcol = [opencol, highcol, lowcol, closecol]
        sort_cols = []
        if 'volume' in df.columns:
            volcol  = pd.DataFrame(df['volume']).resample(freq, how ='sum').dropna()
            allcol.append(volcol)
        if 'date' in df.columns:
            datecol  = pd.DataFrame(df['date']).resample(freq, how ='last').dropna()
            allcol.append(datecol)
            sort_cols.append('date')
        if 'min_id' in df.columns:
            mincol  = pd.DataFrame(df['min_id']).resample(freq, how ='first').dropna()
            allcol.append(mincol)
            sort_cols.append('min_id')
        if 'openInterest' in df.columns:
            volcol  = pd.DataFrame(df['openInterest']).resample(freq, how ='last').dropna()
            allcol.append(volcol)
        if 'contract' in df.columns:
            mincol  = pd.DataFrame(df['contract']).resample(freq, how ='first').dropna()
            allcol.append(mincol)
        res =  pd.concat(allcol, join='outer', axis =1)
        if len(sort_cols) > 0:
            res = res.sort_values(by = sort_cols)
        if index_col == None:
            res = res.reset_index()
    return res

def TR(df):
    tr_df = pd.concat([df['high'] - df['close'], abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))], join='outer', axis=1)
    ts_tr = pd.Series(tr_df.max(1), name='TR')
    return ts_tr

def tr(df_tup):
    df, idx = df_tup
    val = max(df.at[idx,'high'], df.at[idx-1,'close']) - min(df.at[idx,'low'], df.at[idx-1,'close'])
    df.set_value(idx, 'TR', val)
    
def ATR(df, n = 20):
    tr = TR(df)
    ts_atr = pd.ewma(tr, span=n,  min_periods = n-1, adjust = False)
    ts_atr.name = 'ATR'+str(n)
    return ts_atr

def atr(df_tup, n = 20):
    df, idx = df_tup
    new_tr = max(df.at[idx,'high'], df.at[idx-1,'close']) - min(df.at[idx,'low'], df.at[idx-1,'close'])
    alpha = 2.0/(n+1)
    df.set_value(idx,'ATR'+str(n), df.at[idx-1, 'ATR'+str(n)] * (1-alpha) + alpha * new_tr)
    
def tsMA(ts, n):
    return pd.Series(pd.rolling_mean(ts, n), name = 'MA' + str(n))
    
def MA(df, n, field = 'close'):
    return pd.Series(pd.rolling_mean(df[field], n), name = 'MA_' + field[0].upper() + str(n))

def ma(df_tup, n, field = 'close'):
    key = 'MA_' + field[0].upper() + str(n)
    df, idx = df_tup
    df.set_value(idx, key, np.mean(df[field][-n:]))

def STDEV(df, n, field = 'close'):
    return pd.Series(pd.rolling_std(df[field], n), name = 'STDEV_' + field[0].upper() + str(n))

def stdev(df_tup, n, field = 'close'):
    key = 'STDEV_' + field[0].upper() + str(n)
    df, idx = df_tup
    df.set_value(idx, key, np.std(df[field][-n:]))

#Exponential Moving Average
def EMA(df, n, field = 'close'):
    return pd.Series(pd.ewma(df[field], span = n, min_periods = n - 1, adjust = False), name = 'EMA_' + field[0].upper() + str(n))

def ema(df_tup, n, field =  'close'):
    df, idx = df_tup
    alpha = 2.0/(n+1)
    df.set_value(idx, 'EMA_' + field[0].upper() + str(n), df.at[idx-1, 'EMA_' + field[0].upper() + str(n)] * (1-alpha) + df.at[idx, field] * alpha)
    
#Momentum
def MOM(df, n):
    return pd.Series(df['close'].diff(n), name = 'Momentum' + str(n))#Rate of Change

def ROC(df, n):
    M = df['close'].diff(n - 1)
    N = df['close'].shift(n - 1)
    return pd.Series(M / N, name = 'ROC' + str(n))

#Bollinger Bands
def BBANDS(df, n, k = 2):
    MA = pd.Series(pd.rolling_mean(df['close'], n))
    MSD = pd.Series(pd.rolling_std(df['close'], n))
    b1 = 2 * k * MSD / MA
    B1 = pd.Series(b1, name = 'BollingerB' + str(n))
    b2 = (df['close'] - MA + k * MSD) / (2 * k * MSD)
    B2 = pd.Series(b2, name = 'Bollingerb' + str(n))
    return pd.concat([B1,B2], join='outer', axis=1)

#Pivot Points, Supports and Resistances
def PPSR(df):
    PP = pd.Series((df['high'] + df['low'] + df['close']) / 3)
    R1 = pd.Series(2 * PP - df['low'])
    S1 = pd.Series(2 * PP - df['high'])
    R2 = pd.Series(PP + df['high'] - df['low'])
    S2 = pd.Series(PP - df['high'] + df['low'])
    R3 = pd.Series(df['high'] + 2 * (PP - df['low']))
    S3 = pd.Series(df['low'] - 2 * (df['high'] - PP))
    psr = {'PP':PP, 'R1':R1, 'S1':S1, 'R2':R2, 'S2':S2, 'R3':R3, 'S3':S3}
    PSR = pd.DataFrame(psr)
    return PSR

#Stochastic oscillator %K
def STOK(df):
    return pd.Series((df['close'] - df['low']) / (df['high'] - df['low']), name = 'SOk')

#Stochastic oscillator %D
def STO(df, n):
    SOk = STOK(df)
    SOd = pd.Series(pd.ewma(SOk, span = n, min_periods = n - 1, adjust = False), name = 'SOd' + str(n))
    return SOd

#Trix
def TRIX(df, n):
    EX1 = pd.ewma(df['close'], span = n, min_periods = n - 1, adjust = False)
    EX2 = pd.ewma(EX1, span = n, min_periods = n - 1, adjust = False)
    EX3 = pd.ewma(EX2, span = n, min_periods = n - 1, adjust = False)
    return pd.Series(EX3/EX3.shift(1) - 1, name = 'Trix' + str(n))

#Average Directional Movement Index
def ADX(df, n, n_ADX):
    UpMove = df['high'] - df['high'].shift(1)
    DoMove = df['low'].shift(1) - df['low']
    UpD = pd.Series(UpMove)
    DoD = pd.Series(DoMove)
    UpD[(UpMove<=DoMove)|(UpMove <= 0)] = 0
    DoD[(DoMove<=UpMove)|(DoMove <= 0)] = 0
    ATRs = ATR(df,span = n, min_periods = n)
    PosDI = pd.Series(pd.ewma(UpD, span = n, min_periods = n - 1) / ATRs)
    NegDI = pd.Series(pd.ewma(DoD, span = n, min_periods = n - 1) / ATRs)
    ADX = pd.Series(pd.ewma(abs(PosDI - NegDI) / (PosDI + NegDI), span = n_ADX, min_periods = n_ADX - 1), name = 'ADX' + str(n) + '_' + str(n_ADX))
    return ADX 

#MACD, MACD Signal and MACD difference
def MACD(df, n_fast, n_slow):
    EMAfast = pd.Series(pd.ewma(df['close'], span = n_fast, min_periods = n_slow - 1))
    EMAslow = pd.Series(pd.ewma(df['close'], span = n_slow, min_periods = n_slow - 1))
    MACD = pd.Series(EMAfast - EMAslow, name = 'MACD' + str(n_fast) + '_' + str(n_slow))
    MACDsign = pd.Series(pd.ewma(MACD, span = 9, min_periods = 8), name = 'MACDsign' + str(n_fast) + '_' + str(n_slow))
    MACDdiff = pd.Series(MACD - MACDsign, name = 'MACDdiff' + str(n_fast) + '_' + str(n_slow))
    return pd.concat([MACD, MACDsign, MACDdiff], join='outer', axis=1)

#Mass Index
def MassI(df):
    Range = df['high'] - df['low']
    EX1 = pd.ewma(Range, span = 9, min_periods = 8)
    EX2 = pd.ewma(EX1, span = 9, min_periods = 8)
    Mass = EX1 / EX2
    MassI = pd.Series(pd.rolling_sum(Mass, 25), name = 'MassIndex')
    return MassI

#Vortex Indicator
def Vortex(df, n):
    tr = TR(df)
    vm = abs(df['high'] - df['low'].shift(1)) - abs(df['low']-df['high'].shift(1))
    VI = pd.Series(pd.rolling_sum(vm, n) / pd.rolling_sum(tr, n), name = 'Vortex' + str(n))
    return VI

#KST Oscillator
def KST(df, r1, r2, r3, r4, n1, n2, n3, n4):
    M = df['close'].diff(r1 - 1)
    N = df['close'].shift(r1 - 1)
    ROC1 = M / N
    M = df['close'].diff(r2 - 1)
    N = df['close'].shift(r2 - 1)
    ROC2 = M / N
    M = df['close'].diff(r3 - 1)
    N = df['close'].shift(r3 - 1)
    ROC3 = M / N
    M = df['close'].diff(r4 - 1)
    N = df['close'].shift(r4 - 1)
    ROC4 = M / N
    KST = pd.Series(pd.rolling_sum(ROC1, n1) + pd.rolling_sum(ROC2, n2) * 2 + pd.rolling_sum(ROC3, n3) * 3 + pd.rolling_sum(ROC4, n4) * 4, name = 'KST' + str(r1) + '_' + str(r2) + '_' + str(r3) + '_' + str(r4) + '_' + str(n1) + '_' + str(n2) + '_' + str(n3) + '_' + str(n4))
    return KST

#Relative Strength Index
def RSI(df, n):
    UpMove = df['high'] - df['high'].shift(1)
    DoMove = df['low'].shift(1) - df['low']
    UpD = pd.Series(UpMove)
    DoD = pd.Series(DoMove)
    UpD[(UpMove<=DoMove)|(UpMove <= 0)] = 0
    DoD[(DoMove<=UpMove)|(DoMove <= 0)] = 0
    PosDI = pd.Series(pd.ewma(UpD, span = n, min_periods = n - 1))
    NegDI = pd.Series(pd.ewma(DoD, span = n, min_periods = n - 1))
    RSI = pd.Series(PosDI / (PosDI + NegDI), name = 'RSI' + str(n))
    return RSI

#True Strength Index
def TSI(df, r, s):
    M = pd.Series(df['close'].diff(1))
    aM = abs(M)
    EMA1 = pd.Series(pd.ewma(M, span = r, min_periods = r - 1))
    aEMA1 = pd.Series(pd.ewma(aM, span = r, min_periods = r - 1))
    EMA2 = pd.Series(pd.ewma(EMA1, span = s, min_periods = s - 1))
    aEMA2 = pd.Series(pd.ewma(aEMA1, span = s, min_periods = s - 1))
    TSI = pd.Series(EMA2 / aEMA2, name = 'TSI' + str(r) + '_' + str(s))
    return TSI

#Accumulation/Distribution
def ACCDIST(df, n):
    ad = (2 * df['close'] - df['high'] - df['low']) / (df['high'] - df['low']) * df['volume']
    M = ad.diff(n - 1)
    N = ad.shift(n - 1)
    ROC = M / N
    AD = pd.Series(ROC, name = 'Acc/Dist_ROC' + str(n))
    return AD

#Chaikin Oscillator
def Chaikin(df):
    ad = (2 * df['close'] - df['high'] - df['low']) / (df['high'] - df['low']) * df['volume']
    Chaikin = pd.Series(pd.ewma(ad, span = 3, min_periods = 2) - pd.ewma(ad, span = 10, min_periods = 9), name = 'Chaikin')
    return Chaikin

#Money Flow Index and Ratio
def MFI(df, n):
    PP = (df['high'] + df['low'] + df['close']) / 3
    PP = PP.shift(1)
    PosMF = pd.Series(PP)
    PosMF[PosMF <= PosMF.shift(1)] = 0
    PosMF = PosMF * df['volume']
    TotMF = PP * df['volume']
    MFR = pd.Series(PosMF / TotMF)
    MFI = pd.Series(pd.rolling_mean(MFR, n), name = 'MFI' + str(n))
    return MFI

#On-balance Volume
def OBV(df, n):
    PosVol = pd.Series(df['volume'])
    NegVol = pd.Series(-df['volume'])
    PosVol[df['close'] <= df['close'].shift(1)] = 0
    NegVol[df['close'] >= df['close'].shift(1)] = 0
    OBV = pd.Series(pd.rolling_mean(PosVol + NegVol, n), name = 'OBV' + str(n))
    return OBV

#Force Index
def FORCE(df, n):
    F = pd.Series(df['close'].diff(n) * df['volume'].diff(n), name = 'Force' + str(n))
    return F

#Ease of Movement
def EOM(df, n):
    EoM = (df['high'].diff(1) + df['low'].diff(1)) * (df['high'] - df['low']) / (2 * df['volume'])
    Eom_ma = pd.Series(pd.rolling_mean(EoM, n), name = 'EoM' + str(n))
    return Eom_ma

#Commodity Channel Index
def CCI(df, n):
    PP = (df['high'] + df['low'] + df['close']) / 3
    CCI = pd.Series((PP - pd.rolling_mean(PP, n)) / pd.rolling_std(PP, n), name = 'CCI' + str(n))
    return CCI

#Coppock Curve
def COPP(df, n):
    M = df['close'].diff(int(n * 11 / 10) - 1)
    N = df['close'].shift(int(n * 11 / 10) - 1)
    ROC1 = M / N
    M = df['close'].diff(int(n * 14 / 10) - 1)
    N = df['close'].shift(int(n * 14 / 10) - 1)
    ROC2 = M / N
    Copp = pd.Series(pd.ewma(ROC1 + ROC2, span = n, min_periods = n), name = 'Copp' + str(n))
    return Copp

#Keltner Channel
def KELCH(df, n):
    KelChM = pd.Series(pd.rolling_mean((df['high'] + df['low'] + df['close']) / 3, n), name = 'KelChM' + str(n))
    KelChU = pd.Series(pd.rolling_mean((4 * df['high'] - 2 * df['low'] + df['close']) / 3, n), name = 'KelChU' + str(n))
    KelChD = pd.Series(pd.rolling_mean((-2 * df['high'] + 4 * df['low'] + df['close']) / 3, n), name = 'KelChD' + str(n))
    return pd.concat([KelChM, KelChU, KelChD], join='outer', axis=1)

#Ultimate Oscillator
def ULTOSC(df):
    TR_l = TR(df)
    BP_l = df['close'] - pd.concat([df['low'], df['close'].shift(1)], axis=1).min(axis=1)
    UltO = pd.Series((4 * pd.rolling_sum(BP_l, 7) / pd.rolling_sum(TR_l, 7)) + (2 * pd.rolling_sum(BP_l, 14) / pd.rolling_sum(TR_l, 14)) + (pd.rolling_sum(BP_l, 28) / pd.rolling_sum(TR_l, 28)), name = 'UltOsc')
    return UltO

def DONCH_IDX(df, n):
    high = pd.Series(pd.rolling_max(df['high'], n), name = 'DONCH_H'+ str(n))
    low  = pd.Series(pd.rolling_min(df['low'], n), name = 'DONCH_L'+ str(n))
    maxidx = pd.Series(index=df.index, name = 'DONIDX_H%s' % str(n))
    minidx = pd.Series(index=df.index, name = 'DONIDX_L%s' % str(n))
    for idx, dateidx in enumerate(high.index):
        if idx >= (n-1):
            highlist = list(df.iloc[(idx-n+1):(idx+1)]['high'])[::-1]
            maxidx[idx] = highlist.index(high[idx])
            lowlist = list(df.iloc[(idx-n+1):(idx+1)]['low'])[::-1]
            minidx[idx] = lowlist.index(low[idx])
    return pd.concat([high,low, maxidx, minidx], join='outer', axis=1)

def CHENOW_PLUNGER(df, n, atr_n = 40):
    atr = ATR(df, atr_n)
    high = pd.Series((pd.rolling_max(df['high'], n) - df['close'])/atr, name = 'CPLUNGER_H'+ str(n))
    low  = pd.Series((df['close'] - pd.rolling_min(df['low'], n))/atr, name = 'CPLUNGER_L'+ str(n))
    return pd.concat([high,low], join='outer', axis=1)

#Donchian Channel
def DONCH_H(df, n, field = 'high'):
    DC_H = pd.rolling_max(df[field],n)
    return pd.Series(DC_H, name = 'DONCH_H' + field[0].upper() + str(n))

def DONCH_L(df, n, field = 'low'):
    DC_L = pd.rolling_min(df[field], n)
    return pd.Series(DC_L, name = 'DONCH_L'+ field[0].upper() + str(n))

def donch_h(df_tup, n, field = 'high'):
    df, idx = df_tup
    df.set_value(idx, 'DONCH_H'+ field[0].upper() + str(n), max(df[field][-n:]))
 
def donch_l(df_tup, n, field = 'low'):
    df, idx = df_tup
    df.set_value(idx, 'DONCH_L'+ field[0].upper() + str(n), min(df[field][-n:]))
    
#Standard Deviation
#def STDDEV(df, n):
#    return pd.Series(pd.rolling_std(df['close'], n), name = 'STD' + str(n))
def HEIKEN_ASHI(df, period1):
    SM_O = pd.rolling_mean(df['open'], period1)
    SM_H = pd.rolling_mean(df['high'], period1)
    SM_L = pd.rolling_mean(df['low'], period1)
    SM_C = pd.rolling_mean(df['close'], period1)
    HA_C = pd.Series((SM_O + SM_H + SM_L + SM_C)/4.0, name = 'HAclose')
    HA_O = pd.Series(SM_O, name = 'HAopen')
    HA_H = pd.Series(SM_H, name = 'HAhigh')
    HA_L = pd.Series(SM_L, name = 'HAlow')
    for idx, dateidx in enumerate(HA_C.index):
        if idx >= (period1):
            HA_O[idx] = (HA_O[idx-1] + HA_C[idx-1])/2.0
        HA_H[idx] = max(SM_H[idx], HA_O[idx], HA_C[idx])
        HA_L[idx] = min(SM_L[idx], HA_O[idx], HA_C[idx])
    return pd.concat([HA_O, HA_H, HA_L, HA_C], join='outer', axis=1)
    
def heiken_ashi(df_tup, period):
    df, idx = df_tup
    ma_o = sum(df['open'][-period:])/float(period)
    ma_c = sum(df['close'][-period:])/float(period)
    ma_h = sum(df['high'][-period])/float(period)
    ma_l = sum(df['low'][-period:])/float(period)
    df.set_value(idx,'HAclose', (ma_o + ma_c + ma_h + ma_l)/4.0)
    df.set_value(idx, 'HAopen', (df.at[idx-1,'HAopen'] + df.at[idx-1, 'HAclose'])/2.0)
    df.set_value(idx, 'HAhigh', max(ma_h, df.at[idx, 'HAopen'], df.at[idx, 'HAclose']))
    df.set_value(idx, 'HAlow', min(ma_l, df.at[idx, 'HAopen'], df.at[idx, 'HAclose']))

def BBANDS_STOP(df, n, nstd):
    MA = pd.Series(pd.rolling_mean(df['close'], n))
    MSD = pd.Series(pd.rolling_std(df['close'], n))
    Upper = pd.Series(MA + MSD * nstd, name = 'BBSTOP_upper')
    Lower = pd.Series(MA - MSD * nstd, name = 'BBSTOP_lower')
    Trend = pd.Series(0, index = Lower.index, name = 'BBSTOP_trend')
    for idx, dateidx in enumerate(Upper.index):
        if idx >= n:
            Trend[idx] = Trend[idx-1]
            if (df.close[idx] > Upper[idx-1]):
                Trend[idx] = 1
            if (df.close[idx] < Lower[idx-1]):
                Trend[idx] = -1                
            if (Trend[idx]==1) and (Lower[idx] < Lower[idx-1]):
                Lower[idx] = Lower[idx-1]
            elif (Trend[idx]==-1) and (Upper[idx] > Upper[idx-1]):
                Upper[idx] = Upper[idx-1]
    return pd.concat([Upper,Lower, Trend], join='outer', axis=1)

def bbands_stop(df_tup, n, nstd):
    df, idx = df_tup
    ma = df.close[-n:].mean()
    msd = df.close[-n:].std()
    df.set_value(idx, 'BBSTOP_upper', ma + nstd * msd)
    df.set_value(idx, 'BBSTOP_lower', ma - nstd * msd)
    df.set_value(idx, 'BBSTOP_trend', df.at[idx-1, 'BBSTOP_trend'])
    if df.at[idx, 'close'] > df.at[idx-1, 'BBSTOP_upper']:
        df.set_value(idx, 'BBSTOP_trend', 1)
    if df.at[idx, 'close'] < df.at[idx-1, 'BBSTOP_lower']:
        df.set_value(idx, 'BBSTOP_trend', -1)
    if (df.at[idx, 'BBSTOP_trend'] == 1) and (df.at[idx, 'BBSTOP_lower'] < df.at[idx-1, 'BBSTOP_lower']):
        df.set_value(idx, 'BBSTOP_lower', df.at[idx-1, 'BBSTOP_lower'])
    if (df.at[idx, 'BBSTOP_trend'] == -1) and (df.at[idx, 'BBSTOP_upper'] > df.at[idx-1, 'BBSTOP_upper']):
        df.set_value(idx, 'BBSTOP_upper', df.at[idx-1, 'BBSTOP_upper'])

def FISHER(df, n, smooth_p = 0.7, smooth_i = 0.7):
    roll_high = pd.rolling_max(df.high, n)
    roll_low  = pd.rolling_min(df.low, n)
    price_loc = (df.close - roll_low)/(roll_high - roll_low) * 2.0 - 1
    sm_price = pd.Series(pd.ewma(price_loc, com = 1.0/smooth_p - 1, adjust = False), name = 'FISHER_P')
    fisher_ind = 0.5 * np.log((1 + sm_price)/(1 - sm_price))
    sm_fisher = pd.Series(pd.ewma(fisher_ind, com = 1.0/smooth_i - 1, adjust = False), name = 'FISHER_I')
    return pd.concat([sm_price, sm_fisher], join='outer', axis=1)

def fisher(df_tup, n, smooth_p = 0.7, smooth_i = 0.7):
    df, idx = df_tup
    roll_high = max(df.high[-n:])
    roll_low  = min(df.low[-n:])
    price_loc = (df.at[idx, 'close'] - roll_low)*2.0/(roll_high - roll_low) - 1
    df.set_value(idx, 'FISHER_P', df.at[idx-1, 'FISHER_P'] * (1 - smooth_p) + smooth_p * price_loc)
    fisher_ind = 0.5 * np.log((1 + df.at[idx, 'FISHER_P'])/(1 - df.at[idx, 'FISHER_P']))
    df.set_value(idx, 'FISHER_I', df.at[idx-1, 'FISHER_I'] * (1 - smooth_i) + smooth_i * fisher_ind)

def PCT_CHANNEL(df, n = 20, pct = 50, field = 'close'):
    out = pd.Series(index=df.index, name = 'PCT%sCH%s' % (pct, n))
    for idx, d in enumerate(df.index):
        if idx >= n:
            out[d] = np.percentile(df[field].iloc[max(idx-n,0):idx], pct)
    return out

def pct_channel(df_tup, n = 20, pct = 50, field = 'close'):
    key =  'PCT%sCH%s' % (pct, n)
    df, idx = df_tup
    df.set_value(idx, key, np.percentile(df[field].iloc[(-n):], pct))

def COND_PCT_CHAN(df, n = 20, pct = 50, field = 'close', direction=1):
    out = pd.Series(index=df.index, name = 'C_CH%s_PCT%s' % (n, pct))
    for idx, d in enumerate(df.index):
        if idx >= n:
            ts = df[field].iloc[max(idx-n,0):idx]
            cutoff = np.percentile(ts, pct)
            ind = (ts*direction>=cutoff*direction)
            filtered = ts[ind]
            ranks = filtered.rank(ascending=False)
            tot_s = sum([filtered[dt] * ranks[dt] * (seq + 1) for seq, dt in enumerate(filtered.index)])
            tot_w = sum([ranks[dt] * (seq + 1) for seq, dt in enumerate(filtered.index)])    
            out[d] = tot_s/tot_w
    return out
   
def VCI(df, n, rng = 8):
    if n > 7:
        varA = pd.rolling_max(df.high, rng) - pd.rolling_min(df.low, rng)
        varB = varA.shift(rng)
        varC = varA.shift(rng*2)
        varD = varA.shift(rng*3)
        varE = varA.shift(rng*4)
        avg_tr = (varA+varB+varC+varD+varE)/25.0
    else:
        tr = pd.concat([df.high - df.low, abs(df.close - df.close.shift(1))], join='outer', axis=1).max(1)
        avg_tr = pd.rolling_mean(tr, n) * 0.16
    avg_pr = (pd.rolling_mean(df.high, n) + pd.rolling_mean(df.low, n))/2.0
    VO = pd.Series((df.open - avg_pr)/avg_tr, name = 'VCIO')
    VH = pd.Series((df.high - avg_pr)/avg_tr, name = 'VCIH')
    VL = pd.Series((df.low - avg_pr)/avg_tr, name = 'VCIL')
    VC = pd.Series((df.close - avg_pr)/avg_tr, name = 'VCIC')
    return pd.concat([VO, VH, VL, VC], join='outer', axis=1)

def TEMA(ts, n):
    n = int(n)
    ts_ema1 = pd.Series( pd.ewma(ts, span = n, adjust = False), name = 'EMA' + str(n) )
    ts_ema2 = pd.Series( pd.ewma(ts_ema1, span = n, adjust = False), name = 'EMA2' + str(n) )
    ts_ema3 = pd.Series( pd.ewma(ts_ema2, span = n, adjust = False), name = 'EMA3' + str(n) )
    ts_tema = pd.Series( 3 * ts_ema1 - 3 * ts_ema2 + ts_ema3, name = 'TEMA' + str(n) )
    return ts_tema
    
def SVAPO(df, period = 8, cutoff = 1, stdev_h = 1.5, stdev_l = 1.3, stdev_period = 100):
    HA = HEIKEN_ASHI(df, 1)
    haCl = (HA.HAopen + HA.HAclose + HA.HAhigh + HA.HAlow)/4.0
    haC = TEMA( haCl, 0.625 * period )
    vave = tsMA(df['volume'], 5 * period).shift(1)
    vc = pd.concat([df['volume'], vave*2], axis=1).min(axis=1)
    vtrend = TEMA(LINEAR_REG_SLOPE(df.volume, period), period)
    UpD = pd.Series(vc)
    DoD = pd.Series(-vc)
    UpD[(haC<=haC.shift(1)*(1+cutoff/1000.0))|(vtrend < vtrend.shift(1))] = 0
    DoD[(haC>=haC.shift(1)*(1-cutoff/1000.0))|(vtrend > vtrend.shift(1))] = 0
    delta_sum = pd.rolling_sum(UpD + DoD, period)/(vave+1)
    svapo = pd.Series(TEMA(delta_sum, period), name = 'SVAPO_%s' % period)
    svapo_std = pd.rolling_std(svapo, stdev_period)
    svapo_ub = pd.Series(svapo_std * stdev_h, name = 'SVAPO_UB%s' % period)
    svapo_lb = pd.Series(-svapo_std * stdev_l, name = 'SVAPO_LB%s' % period)
    return pd.concat([svapo, svapo_ub, svapo_lb], join='outer', axis=1)

def LINEAR_REG_SLOPE(ts, n):
    sumbars = n*(n-1)*0.5
    sumsqrbars = (n-1)*n*(2*n-1)/6.0
    lrs = pd.Series(index = ts.index, name = 'LINREGSLOPE_%s' % n)
    for idx, d in enumerate(ts.index):
        if idx >= n-1:
            y_array = ts[idx-n+1:idx+1].values
            x_array = np.arange(n-1,-1,-1)
            lrs[idx] = (n * np.dot(x_array, y_array) - sumbars * y_array.sum())/(sumbars*sumbars-n*sumsqrbars)
    return lrs

def DVO(df, w = [0.5, 0.5, 0, 0], N = 2, s = [0.5, 0.5], M = 252):
    ratio = df.close/(df.high * w[0] + df.low * w[1] + df.open * w[2] + df.close * w[3])
    theta = pd.Series(index = df.index)
    dvo = pd.Series(index = df.index, name='DV%s_%s' % (N, M))
    ss = np.array(list(reversed(s)))
    for idx, d in enumerate(ratio.index):
        if idx >= N-1:
            y = ratio[idx-N+1:idx+1].values
            theta[idx] = np.dot(y, ss)
        if idx >= M+N-2:
            ts = theta[idx-(M-1):idx+1]
            dvo[idx] = stats.percentileofscore(ts.values, theta[idx])
    return dvo

def PSAR(df, iaf = 0.02, maxaf = 0.2, incr = 0):
    if incr == 0:
        incr = iaf
    psar = pd.Series(df.close, name='PSAR_VAL')
    direction = pd.Series(index = df.index, name='PSAR_DIR')
    bull = True
    ep = df.low[0]
    hp = df.high[0]
    lp = df.low[0]
    af = iaf
    for idx, d in enumerate(df.index):
        if idx == 0:
            continue
        if bull:
            psar[idx] = psar[idx - 1] + af * (hp - psar[idx - 1])
        else:
            psar[idx] = psar[idx - 1] + af * (lp - psar[idx - 1])
        reverse = False
        if bull:
            if df.low[idx] < psar[idx]:
                bull = False
                reverse = True
                psar[idx] = hp
                lp = df.low[idx]
                af = iaf
        else:
            if df.high[idx] > psar[idx]:
                bull = True
                reverse = True
                psar[idx] = lp
                hp = df.high[idx]
                af = iaf
        if not reverse:
            if bull:
                if df.high[idx] > hp:
                    hp = df.high[idx]
                    af = min(af + incr, maxaf)
                psar[idx] = min(psar[idx], df.low[idx - 1], df.low[idx - 2])

            else:
                if df.low[idx] < lp:
                    lp = df.low[idx]
                    af = min(af + incr, maxaf)
                psar[idx] = max(psar[idx], df.high[idx - 1], df.high[idx - 2])
                direction[idx] = -1
        if bull:
            direction[idx] = 1
        else:
            direction[idx] = -1
    return pd.concat([psar, direction], join='outer', axis=1)
