# encoding: UTF-8

'''
vn.ctp的gateway接入
考虑到现阶段大部分CTP中的ExchangeID字段返回的都是空值
vtSymbol直接使用symbol
'''


import os
import json
from base import *
from misc import *
from vnctpmd import MdApi
from vnctptd import TdApi
from ctpDataType import *
from gateway import *
import logging
import datetime
import order

TERT_RESTART = 0 #从本交易日开始重传
TERT_RESUME = 1 #从上次收到的续传
TERT_QUICK = 2 #只传送登录后的流内容

# 以下为一些VT类型和CTP类型的映射字典
# 价格类型映射
priceTypeMap = {}
priceTypeMap[PRICETYPE_LIMITPRICE] = defineDict["THOST_FTDC_OPT_LimitPrice"]
priceTypeMap[PRICETYPE_MARKETPRICE] = defineDict["THOST_FTDC_OPT_AnyPrice"]
priceTypeMapReverse = {v: k for k, v in priceTypeMap.items()} 

# 方向类型映射
directionMap = {}
directionMap[DIRECTION_LONG] = defineDict['THOST_FTDC_D_Buy']
directionMap[DIRECTION_SHORT] = defineDict['THOST_FTDC_D_Sell']
directionMapReverse = {v: k for k, v in directionMap.items()}

# 开平类型映射
offsetMap = {}
offsetMap[OFFSET_OPEN] = defineDict['THOST_FTDC_OF_Open']
offsetMap[OFFSET_CLOSE] = defineDict['THOST_FTDC_OF_Close']
offsetMap[OFFSET_CLOSETODAY] = defineDict['THOST_FTDC_OF_CloseToday']
offsetMap[OFFSET_CLOSEYESTERDAY] = defineDict['THOST_FTDC_OF_CloseYesterday']
offsetMapReverse = {v:k for k,v in offsetMap.items()}

# 交易所类型映射
exchangeMap = {}
#exchangeMap[EXCHANGE_CFFEX] = defineDict['THOST_FTDC_EIDT_CFFEX']
#exchangeMap[EXCHANGE_SHFE] = defineDict['THOST_FTDC_EIDT_SHFE']
#exchangeMap[EXCHANGE_CZCE] = defineDict['THOST_FTDC_EIDT_CZCE']
#exchangeMap[EXCHANGE_DCE] = defineDict['THOST_FTDC_EIDT_DCE']
exchangeMap[EXCHANGE_CFFEX] = 'CFFEX'
exchangeMap[EXCHANGE_SHFE] = 'SHFE'
exchangeMap[EXCHANGE_CZCE] = 'CZCE'
exchangeMap[EXCHANGE_DCE] = 'DCE'
exchangeMap[EXCHANGE_UNKNOWN] = ''
exchangeMapReverse = {v:k for k,v in exchangeMap.items()}

# 持仓类型映射
posiDirectionMap = {}
posiDirectionMap[DIRECTION_NET] = defineDict["THOST_FTDC_PD_Net"]
posiDirectionMap[DIRECTION_LONG] = defineDict["THOST_FTDC_PD_Long"]
posiDirectionMap[DIRECTION_SHORT] = defineDict["THOST_FTDC_PD_Short"]
posiDirectionMapReverse = {v:k for k,v in posiDirectionMap.items()}

########################################################################
class CtpGateway(Gateway):
    """CTP接口"""

    #----------------------------------------------------------------------
    def __init__(self, agent, gatewayName='CTP'):
        """Constructor"""
        super(CtpGateway, self).__init__(agent, gatewayName)
        
        self.mdApi = CtpMdApi(self)     # 行情API
        self.tdApi = CtpTdApi(self)     # 交易API
        
        self.mdConnected = False        # 行情API连接状态，登录完成后为True
        self.tdConnected = False        # 交易API连接状态
        self.auto_db_update = False
        self.qryEnabled = True         # 是否要启动循环查询
        self.qry_count = 0           # 查询触发倒计时
        self.qry_trigger = 2         # 查询触发点
        self.qry_commands = []
        self.qry_instruments = {}
        self.md_data_buffer = 0
        
    #----------------------------------------------------------------------
    def connect(self):
        """连接"""
        # 载入json文件
        fileName = self.file_prefix + 'connect.json'
        try:
            f = file(fileName)
        except IOError:
            logContent = u'读取连接配置出错，请检查'
            self.onLog(logContent, level = logging.WARNING)
            return

        # 解析json文件
        setting = json.load(f)
        try:
            userID = str(setting['userID'])
            password = str(setting['password'])
            brokerID = str(setting['brokerID'])
            tdAddress = str(setting['tdAddress'])
            mdAddress = str(setting['mdAddress'])
        except KeyError:
            logContent = u'连接配置缺少字段，请检查'
            self.onLog(logContent, level = logging.WARNING)
            return            
        
        # 创建行情和交易接口对象
        self.mdApi.connect(userID, password, brokerID, mdAddress)
        self.mdConnected = False

        self.tdApi.connect(userID, password, brokerID, tdAddress)
        self.tdConnected = False
    
    #----------------------------------------------------------------------
    def subscribe(self, subscribeReq):
        """订阅行情"""
        instID = subscribeReq.symbol
        self.add_instrument(instID)
        self.mdApi.subscribe(instID)
        
    #----------------------------------------------------------------------
    def sendOrder(self, iorder):
        """发单"""
        inst = iorder.instrument
        if not self.order_stats[inst.name]['status']:
            iorder.on_cancel()
            if iorder.trade_ref > 0:
                event = Event(type=EVENT_ETRADEUPDATE)
                event.dict['trade_ref'] = iorder.trade_ref
                self.eventEngine.put(event)
            logContent = 'Canceling order = %s for instrument = %s is disabled for trading due to position control' % (iorder.local_id, inst.name)
            self.onLog( logContent, level = logging.WARNING)
            return
        # 上期所不支持市价单
        if (iorder.price_type == OPT_MARKET_ORDER):
            if (inst.exchange == 'SHFE' or inst.exchange == 'CFFEX'):
                iorder.price_type = OPT_LIMIT_ORDER
                if iorder.direction == ORDER_BUY:
                    iorder.limit_price = inst.up_limit
                else:
                    iorder.limit_price = inst.down_limit
                self.onLog('sending limiting local_id=%s inst=%s for SHFE and CFFEX, change to limit order' % (iorder.local_id, inst.name), level = logging.DEBUG)
            else:
                iorder.limit_price = 0.0
        iorder.status = order.OrderStatus.Sent
        self.tdApi.sendOrder(iorder)
        
        self.order_stats[inst.name]['submit'] += 1
        self.order_stats['total_submit'] += 1

        if self.order_stats[inst.name]['submit'] >= self.order_constraints['submit_limit']:
            self.order_stats[inst.name]['status'] = False
        if self.order_stats['total_submit'] >= self.order_constraints['total_submit']:
            for instID in self.order_stats:
                self.order_stats[instID]['status'] = False
        return

    #----------------------------------------------------------------------
    def cancelOrder(self, iorder):
        """撤单"""
        self.tdApi.cancelOrder(iorder)
        inst = iorder.instrument
        self.order_stats[inst.name]['cancel'] += 1
        self.order_stats['total_cancel'] += 1
        self.onLog( u'A_CC:取消命令: OrderRef=%s, OrderSysID=%s, exchange=%s, instID=%s, volume=%s, filled=%s, cancelled=%s' % (iorder.local_id, \
                            iorder.sys_id, inst.exchange, inst.name, iorder.volume, iorder.filled_volume, iorder.cancelled_volume), level = logging.DEBUG)     		
        
    #----------------------------------------------------------------------
    def qryAccount(self):
        """查询账户资金"""
        self.tdApi.qryAccount()
        
    #----------------------------------------------------------------------
    def qryPosition(self):
        """查询持仓"""
        self.tdApi.qryPosition()
        
    #----------------------------------------------------------------------
    def close(self):
        """关闭"""
        if self.mdConnected:
            self.mdApi.close()
        if self.tdConnected:
            self.tdApi.close()
    
    #----------------------------------------------------------------------
    def query(self, event):
        """注册到事件处理引擎上的查询函数"""
        if self.qryEnabled:
            self.qry_count += 1
            if self.qry_count > self.qry_trigger:
                self.qryCount = 0
                if len(self.qry_commands)>0:
                    self.qry_commands[0]()
                    del self.qry_commands[0]
    
    #----------------------------------------------------------------------
    def setQryEnabled(self, qryEnabled):
        """设置是否要启动循环查询"""
        self.qryEnabled = qryEnabled

    def setAutoDbUpdated(self, db_update):
        self.auto_db_update = db_update

    def register_event_handler(self):
        self.eventEngine.register(EVENT_MARKETDATA+self.gatewayName, self.rsp_market_data)
        self.eventEngine.register(EVENT_QRYACCOUNT+self.gatewayName, self.rsp_qry_account)
        self.eventEngine.register(EVENT_QRYPOSITION+self.gatewayName, self.rsp_qry_position)
        self.eventEngine.register(EVENT_QRYTRADE+self.gatewayName, self.rsp_qry_order)
        self.eventEngine.register(EVENT_QRYORDER+self.gatewayName, self.rsp_qry_order)
        self.eventEngine.register(EVENT_QRYINVESTOR+self.gatewayName, self.rsp_qry_investor)
        self.eventEngine.register(EVENT_QRYINSTRUMENT+self.gatewayName, self.rsp_qry_instrument)
        self.eventEngine.register(EVENT_ERRORDERCANCEL+self.gatewayName, self.err_order_insert)
        self.eventEngine.register(EVENT_ERRORDERINSERT+self.gatewayName, self.err_order_action)
        self.eventEngine.register(EVENT_RTNTRADE+self.gatewayName, self.rtn_trade)
        self.eventEngine.register(EVENT_RTNORDER+self.gatewayName, self.rtn_order)
        self.eventEngine.register(EVENT_TIMER, self.query)
        self.eventEngine.register(EVENT_TDLOGIN+self.gatewayName, self.rsp_td_login)

    def rsp_td_login(self, event):
        self.qry_commands.append(self.tdApi.qryAccount)
        self.qry_commands.append(self.tdApi.qryPosition)
        self.qry_commands.append(self.tdApi.qryOrder)
        self.qry_commands.append(self.tdApi.qryTrade)

    def onOrder(self, order):
        pass

    def onTrade(self, trade):
        pass

    def rtn_order(self, event):
        data = event.dict['data']
        newref = data['OrderRef']
        if not newref.isdigit():
            return
        local_id = int(newref)
        self.tdApi.orderRef = max(self.tdApi.orderRef, local_id)
        if (local_id in self.id2order):
            myorder = self.id2order[local_id]
            # only update sysID,
            status = myorder.on_order(sys_id = data['OrderSysID'], price = data['LimitPrice'], volume = 0)
            if data['OrderStatus'] in [ '5', '2']:
                myorder.on_cancel()
                status = True
            if myorder.trade_ref <= 0:
                order = VtOrderData()
                order.gatewayName = self.gatewayName
                # 保存代码和报单号
                order.symbol = data['InstrumentID']
                order.exchange = exchangeMapReverse[data['ExchangeID']]
                order.instID = order.symbol #'.'.join([order.symbol, order.exchange])
                order.orderID = local_id
                order.orderSysID = data['OrderSysID']
                # 方向
                if data['Direction'] == '0':
                    order.direction = DIRECTION_LONG
                elif data['Direction'] == '1':
                    order.direction = DIRECTION_SHORT
                else:
                    order.direction = DIRECTION_UNKNOWN
                # 开平
                if data['CombOffsetFlag'] == '0':
                    order.offset = OFFSET_OPEN
                elif data['CombOffsetFlag'] == '1':
                    order.offset = OFFSET_CLOSE
                else:
                    order.offset = OFFSET_UNKNOWN
                # 状态
                if data['OrderStatus'] == '0':
                    order.status = STATUS_ALLTRADED
                elif data['OrderStatus'] == '1':
                    order.status = STATUS_PARTTRADED
                elif data['OrderStatus'] == '3':
                    order.status = STATUS_NOTTRADED
                elif data['OrderStatus'] == '5':
                    order.status = STATUS_CANCELLED
                else:
                    order.status = STATUS_UNKNOWN
                # 价格、报单量等数值
                order.price = data['LimitPrice']
                order.totalVolume = data['VolumeTotalOriginal']
                order.tradedVolume = data['VolumeTraded']
                order.orderTime = data['InsertTime']
                order.cancelTime = data['CancelTime']
                order.frontID = data['FrontID']
                order.sessionID = data['SessionID']
                order.order_ref = myorder.order_ref
                self.onOrder(order)
                return
            else:
                if status:
                    event = Event(type=EVENT_ETRADEUPDATE)
                    event.dict['trade_ref'] = myorder.trade_ref
                    self.eventEngine.put(event)
        else:
            logContent = 'receive order update from other agents, InstID=%s, OrderRef=%s' % (data['InstrumentID'], local_id)
            self.onLog(logContent, level = logging.WARNING)

    def rtn_trade(self, event):
        data = event.dict['data']
        newref = data['OrderRef']
        if not newref.isdigit():
            return
        local_id = int(newref)
        if local_id in self.id2order:
            myorder = self.id2order[local_id]
            myorder.on_trade(price = data['Price'], volume=data['Volume'], trade_id = data['TradeID'])
            if myorder.trade_ref <= 0:
                trade = VtTradeData()
                trade.gatewayName = self.gatewayName
                # 保存代码和报单号
                trade.symbol = data['InstrumentID']
                trade.exchange = exchangeMapReverse[data['ExchangeID']]
                trade.vtSymbol = trade.symbol #'.'.join([trade.symbol, trade.exchange])
                trade.tradeID = data['TradeID']
                trade.vtTradeID = '.'.join([self.gatewayName, trade.tradeID])
                trade.orderID = local_id
                trade.order_ref = myorder.order_ref
                # 方向
                trade.direction = directionMapReverse.get(data['Direction'], '')
                # 开平
                trade.offset = offsetMapReverse.get(data['OffsetFlag'], '')
                # 价格、报单量等数值
                trade.price = data['Price']
                trade.volume = data['Volume']
                trade.tradeTime = data['TradeTime']
                # 推送
                self.onTrade(trade)
            else:
                event = Event(type=EVENT_ETRADEUPDATE)
                event.dict['trade_ref'] = myorder.trade_ref
                self.eventEngine.put(event)
        else:
            logContent = 'receive trade update from other agents, InstID=%s, OrderRef=%s' % (data['InstrumentID'], local_id)
            self.onLog(logContent, level = logging.WARNING)

    def rsp_market_data(self, event):
        data = event.dict['data']
        if self.mdApi.trading_day == 0:
            self.mdApi.trading_day = int(data['TradingDay'])
        timestr = str(self.mdApi.trading_day) + ' '+ str(data['UpdateTime']) + ' ' + str(data['UpdateMillisec']) + '000'
        try:
            timestamp = datetime.datetime.strptime(timestr, '%Y%m%d %H:%M:%S %f')
        except:
            logContent =  "Error to convert timestr = %s" % timestr
            self.onLog(logContent, level = logging.INFO)
            return
        tick_id = get_tick_id(timestamp)
        if data['ExchangeID'] == 'CZCE':
            if (len(data['TradingDay'])>0):
                if (self.trading_day > int(data['TradingDay'])) and (tick_id >= 600000):
                    rtn_error = BaseObject(errorMsg="tick data is wrong, %s" % data)
                    self.onError(rtn_error)
                    return
        tick = VtTickData()
        tick.gatewayName = self.gatewayName
        tick.symbol = data['InstrumentID']
        tick.instID = tick.symbol #'.'.join([tick.symbol, EXCHANGE_UNKNOWN])
        tick.exchange = exchangeMapReverse.get(data['ExchangeID'], u'未知')
        product = inst2product(tick.instID)
        hrs = trading_hours(product, tick.exchange)
        tick_status = True
        bad_tick = True
        for ptime in hrs:
            if (tick_id>=ptime[0]*1000-self.md_data_buffer) and (tick_id< ptime[1]*1000+self.md_data_buffer):
                bad_tick = False
                break
        if bad_tick:
            return
        tick.timestamp = timestamp
        tick.date = timestamp.date()
        tick.tick_id = tick_id
        tick.price = data['LastPrice']
        tick.volume = data['Volume']
        tick.openInterest = data['OpenInterest']
        # CTP只有一档行情
        tick.open = data['OpenPrice']
        tick.high = data['HighestPrice']
        tick.low = data['LowestPrice']
        tick.prev_close = data['PreClosePrice']
        tick.upLimit = data['UpperLimitPrice']
        tick.downLimit = data['LowerLimitPrice']
        tick.bidPrice1 = data['BidPrice1']
        tick.bidVol1 = data['BidVolume1']
        tick.askPrice1 = data['AskPrice1']
        tick.askVol1 = data['AskVolume1']
        # 通用事件
        event1 = Event(type=EVENT_TICK)
        event1.dict['data'] = tick
        self.eventEngine.put(event1)
        
        # 特定合约代码的事件
        event2 = Event(type=EVENT_TICK+tick.instID)
        event2.dict['data'] = tick
        self.eventEngine.put(event2)

    def rsp_qry_account(self, event):
        data = event.dict['data']
        self.qry_account['preBalance'] = data['PreBalance']
        self.qry_account['available'] = data['Available']
        self.qry_account['commission'] = data['Commission']
        self.qry_account['margin'] = data['CurrMargin']
        self.qry_account['closeProfit'] = data['CloseProfit']
        self.qry_account['positionProfit'] = data['PositionProfit']
        
        # 这里的balance和快期中的账户不确定是否一样，需要测试
        self.qry_account['balance'] = (data['PreBalance'] - data['PreCredit'] - data['PreMortgage'] +
                           data['Mortgage'] - data['Withdraw'] + data['Deposit'] +
                           data['CloseProfit'] + data['PositionProfit'] + data['CashIn'] -
                           data['Commission'])

    def rsp_qry_instrument(self, event):
        data = event.dict['data']
        last = event.dict['last']
        if data['ProductClass'] == '1' and data['ExchangeID'] in ['CZCE', 'DCE', 'SHFE', 'CFFEX']:
            cont = {}
            cont['instID'] = data['InstrumentID']			
            cont['margin_l'] = data['LongMarginRatio']
            cont['margin_s'] = data['ShortMarginRatio']
            cont['start_date'] =data['OpenDate']
            cont['expiry'] = data['ExpireDate']
            cont['product_code'] = data['ProductID']
            #cont['exchange'] = data['ExchangeID']
            instID = cont['instID']
            self.qry_instruments[instID] = cont
        if last and self.auto_db_update:
            print "update contract table, new inst # = %s" % len(self.qry_instruments)
            for instID in self.qry_instruments:
                mysqlaccess.insert_cont_data(self.qry_instruments[instID])

    def rsp_qry_investor(self, event):
        pass

    def rsp_qry_position(self, event):
        pposition = event.dict['data']
        isLast = event.dict['last']
        instID = pposition['InstrumentID']
        if len(instID) ==0:
            return
        if (instID not in self.qry_pos):
            self.qry_pos[instID]   = {'tday': [0, 0], 'yday': [0, 0]}
        key = 'yday'
        idx = 1
        if pposition['PosiDirection'] == '2':
            if pposition['PositionDate'] == '1':
                key = 'tday'
                idx = 0
            else:
                idx = 0
        else:
            if pposition['PositionDate'] == '1':
                key = 'tday'
        self.qry_pos[instID][key][idx] = pposition['Position']
        self.qry_pos[instID]['yday'][idx] = pposition['YdPosition']
        if isLast:
            print self.qry_pos

    def rsp_qry_order(self, event):
        sorder = event.dict['data']
        isLast = event.dict['last']
        if (len(sorder['OrderRef']) == 0):
            return
        if not sorder['OrderRef'].isdigit():
            return
        local_id = int(sorder['OrderRef'])
        if (local_id in self.id2order):
            iorder = self.id2order[local_id]
            self.system_orders.append(local_id)
            if iorder.status not in [order.OrderStatus.Cancelled, order.OrderStatus.Done]:
                status = iorder.on_order(sys_id = sorder['OrderSysID'], price = sorder['LimitPrice'], volume = sorder['VolumeTraded'])
                if status:
                    event = Event(type=EVENT_ETRADEUPDATE)
                    event.dict['trade_ref'] = iorder.trade_ref
                    self.eventEngine.put(event)
                elif sorder.OrderStatus in ['3', '1', 'a']:
                    if iorder.status != order.OrderStatus.Sent or iorder.conditionals != {}:
                        iorder.status = order.OrderStatus.Sent
                        iorder.conditionals = {}
                        logContent = 'order status for OrderSysID = %s, Inst=%s is set to %s, but should be waiting in exchange queue' % (iorder.sys_id, iorder.instrument.name, iorder.status)
                        self.onLog(logContent, level = logging.INFO)
                elif sorder.OrderStatus in ['5', '2', '4']:
                    if iorder.status != order.OrderStatus.Cancelled:
                        iorder.on_cancel()
                        event = Event(type=EVENT_ETRADEUPDATE)
                        event.dict['trade_ref'] = iorder.trade_ref
                        self.eventEngine.put(event)
                        logContent = 'order status for OrderSysID = %s, Inst=%s is set to %s, but should be waiting in exchange queue' % (iorder.sys_id, iorder.instrument.name, iorder.status)
                        self.onLog(logContent, level = logging.INFO)

        if isLast:
            for local_id in self.id2order:
                if (local_id not in self.system_orders):
                    iorder = self.id2order[local_id]
                    iorder.on_cancel()
                    event = Event(type=EVENT_ETRADEUPDATE)
                    event.dict['trade_ref'] = iorder.trade_ref
                    self.eventEngine.put(event)
            self.system_orders = []

    def err_order_insert(self, event):
        '''
            ctp/交易所下单错误回报，不区分ctp和交易所正常情况下不应当出现
        '''
        porder = event.dict['data']
        error = event.dict['error']
        if not porder['OrderRef'].isdigit():
            return
        local_id = int(porder['OrderRef'])
        inst = porder['InstrumentID']
        if local_id in self.id2order:
            myorder = self.id2order[local_id]
            myorder.on_cancel()
            event = Event(type=EVENT_ETRADEUPDATE)
            event.dict['trade_ref'] = myorder.trade_ref
            self.eventEngine.put(event)
        logContent = 'OrderInsert is not accepted by CTP, local_id=%s, instrument=%s, error=%s. ' % (local_id, inst, error['ErrorMsg'])
        if inst not in self.order_stats:
            self.order_stats[inst] = {'submit': 0, 'cancel':0, 'failure': 0, 'status': True }
        self.order_stats[inst]['failure'] += 1
        #self.order_stats['total_failure'] += 1
        if self.order_stats[inst]['failure'] >= self.order_constraints['failure_limit']:
            self.order_stats[inst]['status'] = False
            logContent += 'Failed order reaches the limit, disable instrument = %s' % inst
        self.onLog(logContent, level = logging.WARNING)

    def err_order_action(self, event):
        '''
            ctp/交易所撤单错误回报，不区分ctp和交易所必须处理，如果已成交，撤单后必然到达这个位置
        '''
        porder = event.dict['data']
        error = event.dict['error']
        inst = porder['InstrumentID']
        logContent = 'Order Cancel is wrong, local_id=%s, instrument=%s, error=%s. ' % (porder['OrderRef'], inst, error['ErrorMsg'])
        if porder['OrderRef'].isdigit():
            local_id = int(porder['OrderRef'])
            myorder = self.id2order[local_id]
            if int(error['ErrorID']) in [25,26] and myorder.status not in [order.OrderStatus.Cancelled, order.OrderStatus.Done]:
                myorder.on_cancel()
                event = Event(type=EVENT_ETRADEUPDATE)
                event.dict['trade_ref'] = myorder.trade_ref
                self.eventEngine.put(event)
        else:
            self.qry_commands.append(self.tdApi.qryOrder)
        if inst not in self.order_stats:
            self.order_stats[inst] = {'submit': 0, 'cancel':0, 'failure': 0, 'status': True }
        self.order_stats[inst]['failure'] += 1
        #self.order_stats['total_failure'] += 1
        if self.order_stats[inst]['failure'] >= self.order_constraints['failure_limit']:
            self.order_stats[inst]['status'] = False
            logContent += 'Failed order reaches the limit, disable instrument = %s' % inst
        self.onLog(logContent, level = logging.WARNING)

########################################################################
class CtpMdApi(MdApi):
    """CTP行情API实现"""

    #----------------------------------------------------------------------
    def __init__(self, gateway):
        """Constructor"""
        super(CtpMdApi, self).__init__()
        
        self.gateway = gateway                  # gateway对象
        self.gatewayName = gateway.gatewayName  # gateway对象名称
        self.reqID = EMPTY_INT              # 操作请求编号
        self.connectionStatus = False       # 连接状态
        self.loginStatus = False            # 登录状态
        self.userID = EMPTY_STRING          # 账号
        self.password = EMPTY_STRING        # 密码
        self.brokerID = EMPTY_STRING        # 经纪商代码
        self.address = EMPTY_STRING         # 服务器地址
        self.trading_day = 20160101
        
    #----------------------------------------------------------------------
    def onFrontConnected(self):
        """服务器连接"""
        self.connectionStatus = True
        logContent = u'行情服务器连接成功'
        self.gateway.onLog(logContent, level = logging.INFO)
        self.login()
    
    #----------------------------------------------------------------------  
    def onFrontDisconnected(self, n):
        """服务器断开"""
        self.connectionStatus = False
        self.loginStatus = False
        self.gateway.mdConnected = False
        logContent = u'行情服务器连接断开'
        self.gateway.onLog(logContent, level = logging.INFO)      
        
    #---------------------------------------------------------------------- 
    def onHeartBeatWarning(self, n):
        """心跳报警"""
        # 因为API的心跳报警比较常被触发，且与API工作关系不大，因此选择忽略
        pass
    
    #----------------------------------------------------------------------   
    def onRspError(self, error, n, last):
        """错误回报"""
        err = VtErrorData()
        err.gatewayName = self.gatewayName
        err.errorID = error['ErrorID']
        err.errorMsg = error['ErrorMsg'].decode('gbk')
        self.gateway.onError(err)
        
    #----------------------------------------------------------------------
    def onRspUserLogin(self, data, error, n, last):
        """登陆回报"""
        # 如果登录成功，推送日志信息
        if (error['ErrorID'] == 0) and last:
            self.loginStatus = True
            self.gateway.mdConnected = True
            logContent = u'行情服务器登录完成'
            self.gateway.onLog(logContent, level = logging.INFO)
            # 重新订阅之前订阅的合约
            for instID in self.gateway.instruments:
                self.subscribe(instID)
            trade_day_str = self.getTradingDay()
            if len(trade_day_str) > 0:
                try:
                    self.trading_day = int(trade_day_str)
                    tradingday = datetime.datetime.strptime(trade_day_str, '%Y%m%d').date()
                    if tradingday > self.gateway.agent.scur_day:
                        event = Event(type=EVENT_DAYSWITCH)
                        event.dict['log'] = u'换日: %s -> %s' % (self.gateway.agent.scur_day, self.trading_day)
                        event.dict['date'] = tradingday
                        self.gateway.eventEngine.put(event)
                except ValueError:
                    pass
        # 否则，推送错误信息
        else:
            err = VtErrorData()
            err.gatewayName = self.gatewayName
            err.errorID = error['ErrorID']
            err.errorMsg = error['ErrorMsg'].decode('gbk')
            self.gateway.onError(err)
                
    #---------------------------------------------------------------------- 
    def onRspUserLogout(self, data, error, n, last):
        """登出回报"""
        # 如果登出成功，推送日志信息
        if error['ErrorID'] == 0:
            self.loginStatus = False
            self.gateway.tdConnected = False
            logContent = u'行情服务器登出完成'
            self.gateway.onLog(logContent, level = logging.INFO)
                
        # 否则，推送错误信息
        else:
            err = VtErrorData()
            err.gatewayName = self.gatewayName
            err.errorID = error['ErrorID']
            err.errorMsg = error['ErrorMsg'].decode('gbk')
            self.gateway.onError(err)
        
    #----------------------------------------------------------------------  
    def onRspSubMarketData(self, data, error, n, last):
        """订阅合约回报"""
        # 通常不在乎订阅错误，选择忽略
        pass
        
    #----------------------------------------------------------------------  
    def onRspUnSubMarketData(self, data, error, n, last):
        """退订合约回报"""
        # 同上
        pass  
        
    #----------------------------------------------------------------------  
    def onRtnDepthMarketData(self, data):
        """行情推送"""
        if (data['LastPrice'] > data['UpperLimitPrice']) or (data['LastPrice'] < data['LowerLimitPrice']) or \
                (data['AskPrice1'] >= data['UpperLimitPrice'] and data['BidPrice1'] <= data['LowerLimitPrice']) or \
                (data['BidPrice1'] >= data['AskPrice1']):
            logContent = u'MD:error in market data for %s LastPrice=%s, BidPrice=%s, AskPrice=%s' % \
                             (data['InstrumentID'], data['LastPrice'], data['BidPrice1'], data['AskPrice1'])
            self.gateway.onLog(logContent, level = logging.DEBUG)
            return
        event = Event(type = EVENT_MARKETDATA + self.gatewayName)
        event.dict['data'] = data
        event.dict['gateway'] = self.gatewayName
        self.gateway.eventEngine.put(event)
        
    #---------------------------------------------------------------------- 
    def onRspSubForQuoteRsp(self, data, error, n, last):
        """订阅期权询价"""
        pass
        
    #----------------------------------------------------------------------
    def onRspUnSubForQuoteRsp(self, data, error, n, last):
        """退订期权询价"""
        pass 
        
    #---------------------------------------------------------------------- 
    def onRtnForQuoteRsp(self, data):
        """期权询价推送"""
        pass        
        
    #----------------------------------------------------------------------
    def connect(self, userID, password, brokerID, address):
        """初始化连接"""
        self.userID = userID                # 账号
        self.password = password            # 密码
        self.brokerID = brokerID            # 经纪商代码
        self.address = address              # 服务器地址

        # 如果尚未建立服务器连接，则进行连接
        if not self.connectionStatus:
            # 创建C++环境中的API对象，这里传入的参数是需要用来保存.con文件的文件夹路径
            path = self.gateway.file_prefix + 'tmp' + os.path.sep
            if not os.path.exists(path):
                os.makedirs(path)

            self.createFtdcMdApi(str(path))
            # 注册服务器地址
            self.registerFront(self.address)
            
            # 初始化连接，成功会调用onFrontConnected
            self.init()
            
        # 若已经连接但尚未登录，则进行登录
        else:
            if not self.loginStatus:
                self.login()
        
    #----------------------------------------------------------------------
    def subscribe(self, symbol):
        """订阅合约"""
        # 这里的设计是，如果尚未登录就调用了订阅方法
        # 则先保存订阅请求，登录完成后会自动订阅
        if self.loginStatus:
            self.subscribeMarketData(str(symbol))
        if symbol not in self.gateway.instruments:
            self.gateway.instruments.append(symbol)
        
    #----------------------------------------------------------------------
    def login(self):
        """登录"""
        # 如果填入了用户名密码等，则登录
        if self.userID and self.password and self.brokerID:
            req = {}
            req['UserID'] = self.userID
            req['Password'] = self.password
            req['BrokerID'] = self.brokerID
            self.reqID += 1
            self.reqUserLogin(req, self.reqID)    
    
    #----------------------------------------------------------------------
    def close(self):
        """关闭"""
        self.exit()


########################################################################
class CtpTdApi(TdApi):
    """CTP交易API实现"""
    
    #----------------------------------------------------------------------
    def __init__(self, gateway):
        """API对象的初始化函数"""
        super(CtpTdApi, self).__init__()
        
        self.gateway = gateway                  # gateway对象
        self.gatewayName = gateway.gatewayName  # gateway对象名称
        
        self.reqID = EMPTY_INT              # 操作请求编号
        self.orderRef = EMPTY_INT           # 订单编号
        
        self.connectionStatus = False       # 连接状态
        self.loginStatus = False            # 登录状态
        
        self.userID = EMPTY_STRING          # 账号
        self.password = EMPTY_STRING        # 密码
        self.brokerID = EMPTY_STRING        # 经纪商代码
        self.address = EMPTY_STRING         # 服务器地址
        
        self.frontID = EMPTY_INT            # 前置机编号
        self.sessionID = EMPTY_INT          # 会话编号
        
    #----------------------------------------------------------------------
    def onFrontConnected(self):
        """服务器连接"""
        self.connectionStatus = True
        logContent = u'交易服务器连接成功'
        self.gateway.onLog(logContent, level = logging.INFO)
        
        self.login()
    
    #----------------------------------------------------------------------
    def onFrontDisconnected(self, n):
        """服务器断开"""
        self.connectionStatus = False
        self.loginStatus = False
        self.gateway.tdConnected = False

        logContent = u'交易服务器连接断开'
        self.gateway.onLog(logContent, level = logging.INFO)
    
    #----------------------------------------------------------------------
    def onHeartBeatWarning(self, n):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspAuthenticate(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspUserLogin(self, data, error, n, last):
        """登陆回报"""
        # 如果登录成功，推送日志信息
        if error['ErrorID'] == 0:
            self.frontID = str(data['FrontID'])
            self.sessionID = str(data['SessionID'])
            self.loginStatus = True
            logContent = u'交易服务器登录完成'
            self.gateway.onLog(logContent, level = logging.INFO)
            
            # 确认结算信息
            req = {}
            req['BrokerID'] = self.brokerID
            req['InvestorID'] = self.userID
            self.reqID += 1
            self.reqSettlementInfoConfirm(req, self.reqID)			
                
        # 否则，推送错误信息
        else:
            self.loginStatus = False
            self.gateway.tdConnected = False
            err = VtErrorData()
            err.gatewayName = self.gateway
            err.errorID = error['ErrorID']
            err.errorMsg = error['ErrorMsg'].decode('gbk')
            self.gateway.onError(err)			
            time.sleep(30)
            self.login()
    
    #----------------------------------------------------------------------
    def onRspUserLogout(self, data, error, n, last):
        """登出回报"""
        # 如果登出成功，推送日志信息
        if error['ErrorID'] == 0:
            self.loginStatus = False
            self.gateway.tdConnected = False
            logContent = u'交易服务器登出完成'
            self.gateway.onLog(logContent, level = logging.INFO)
                
        # 否则，推送错误信息
        else:
            err = VtErrorData()
            err.gatewayName = self.gatewayName
            err.errorID = error['ErrorID']
            err.errorMsg = error['ErrorMsg'].decode('gbk')
            self.gateway.onError(err)
    
    #----------------------------------------------------------------------
    def onRspUserPasswordUpdate(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspTradingAccountPasswordUpdate(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspOrderInsert(self, data, error, n, last):
        """发单错误（柜台）"""
        err = VtErrorData()
        err.gatewayName = self.gatewayName
        err.errorID = error['ErrorID']
        err.errorMsg = error['ErrorMsg'].decode('gbk')
        self.gateway.onError(err)

        event2 = Event(type=EVENT_ERRORDERINSERT + self.gatewayName)
        event2.dict['data'] = data
        event2.dict['error'] = error
        event2.dict['gateway'] = self.gatewayName
        self.gateway.eventEngine.put(event2)
    
    #----------------------------------------------------------------------
    def onRtnOrder(self, data):
        """报单回报"""
        # 更新最大报单编号
        event = Event(type=EVENT_RTNORDER + self.gatewayName)
        event.dict['data'] = data
        self.gateway.eventEngine.put(event)
    
    #----------------------------------------------------------------------
    def onRtnTrade(self, data):
        """成交回报"""
        # 创建报单数据对象
        event = Event(type=EVENT_RTNTRADE+self.gatewayName)
        event.dict['data'] = data
        self.gateway.eventEngine.put(event)
    
    #----------------------------------------------------------------------
    def onErrRtnOrderInsert(self, data, error):
        """发单错误回报（交易所）"""
        event = Event(type=EVENT_ERRORDERINSERT + self.gatewayName)
        event.dict['data'] = data
        event.dict['error'] = error
        self.gateway.eventEngine.put(event)

        err = VtErrorData()
        err.gatewayName = self.gatewayName
        err.errorID = error['ErrorID']
        err.errorMsg = error['ErrorMsg'].decode('gbk')
        self.gateway.onError(err)
    
    #----------------------------------------------------------------------
    def onErrRtnOrderAction(self, data, error):
        """撤单错误回报（交易所）"""
        event = Event(type=EVENT_ERRORDERCANCEL + self.gatewayName)
        event.dict['data'] = data
        event.dict['error'] = error
        event.dict['gateway'] = self.gatewayName
        self.gateway.eventEngine.put(event)

        err = VtErrorData()
        err.gatewayName = self.gatewayName
        err.errorID = error['ErrorID']
        err.errorMsg = error['ErrorMsg'].decode('gbk')
        self.gateway.onError(err)

    #----------------------------------------------------------------------
    def onRspOrderAction(self, data, error, n, last):
        """撤单错误（柜台）"""
        err = VtErrorData()
        err.gatewayName = self.gatewayName
        err.errorID = error['ErrorID']
        err.errorMsg = error['ErrorMsg'].decode('gbk')
        self.gateway.onError(err)

        event2 = Event(type=EVENT_ERRORDERCANCEL + self.gatewayName)
        event2.dict['data'] = data
        event2.dict['error'] = error
        event2.dict['gateway'] = self.gatewayName
        self.gateway.eventEngine.put(event2)

    #----------------------------------------------------------------------
    def onRspQueryMaxOrderVolume(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspSettlementInfoConfirm(self, data, error, n, last):
        """确认结算信息回报"""
        self.gateway.tdConnected = True
        event = Event(type=EVENT_TDLOGIN+self.gatewayName)
        self.gateway.eventEngine.put(event)

        # 查询合约代码
        # self.reqID += 1
        # self.reqQryInstrument({}, self.reqID)
        logContent = u'结算信息确认完成'
        self.gateway.onLog(logContent, level = logging.INFO)
    
    #----------------------------------------------------------------------
    def onRspQryTradingAccount(self, data, error, n, last):
        """资金账户查询回报"""
        if error['ErrorID'] == 0:
            event = Event(type=EVENT_QRYACCOUNT + self.gatewayName )
            event.dict['data'] = data
            event.dict['last'] = last
            self.gateway.eventEngine.put(event)
        else:
            logContent = u'资金账户查询回报，错误代码：' + unicode(error['ErrorID']) + u',' + u'错误信息：' + error['ErrorMsg'].decode('gbk')
            self.gateway.onLog(logContent, level = logging.DEBUG)

    #----------------------------------------------------------------------
    def onRspParkedOrderInsert(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspParkedOrderAction(self, data, error, n, last):
        """"""
        pass
        
    #----------------------------------------------------------------------
    def onRspRemoveParkedOrder(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspRemoveParkedOrderAction(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspExecOrderInsert(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspExecOrderAction(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspForQuoteInsert(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQuoteInsert(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQuoteAction(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryOrder(self, data, error, n, last):
        """"""
        '''请求查询报单响应'''
        if error['ErrorID'] == 0:
            event = Event(type=EVENT_QRYORDER + self.gatewayName )
            event.dict['data'] = data
            event.dict['last'] = last
            self.gateway.eventEngine.put(event)
        else:
            logContent = u'交易错误回报，错误代码：' + unicode(error['ErrorID']) + u',' + u'错误信息：' + error['ErrorMsg'].decode('gbk')
            self.gateway.onLog(logContent, level = logging.DEBUG)
    
    #----------------------------------------------------------------------
    def onRspQryTrade(self, data, error, n, last):
        """"""
        if error['ErrorID'] == 0:
            event = Event(type=EVENT_QRYTRADE + self.gatewayName )
            event.dict['data'] = data
            event.dict['last'] = last
            self.gateway.eventEngine.put(event)
        else:
            event = Event(type=EVENT_LOG)
            logContent = u'交易错误回报，错误代码：' + unicode(error['ErrorID']) + u',' + u'错误信息：' + error['ErrorMsg'].decode('gbk')
            self.gateway.onLog(logContent, level = logging.DEBUG)
    
    #----------------------------------------------------------------------
    def onRspQryInvestorPosition(self, data, error, n, last):
        """持仓查询回报"""
        if error['ErrorID'] == 0:
            event = Event(type=EVENT_QRYPOSITION + self.gatewayName )
            event.dict['data'] = data
            event.dict['last'] = last
            self.gateway.eventEngine.put(event)
        else:
            logContent = u'持仓查询回报，错误代码：' + unicode(error['ErrorID']) + u',' + u'错误信息：' + error['ErrorMsg'].decode('gbk')
            self.gateway.onLog(logContent, level = logging.DEBUG)

    #----------------------------------------------------------------------
    def onRspQryInvestor(self, data, error, n, last):
        """投资者查询回报"""
        if error['ErrorID'] == 0:
            event = Event(type=EVENT_QRYINVESTOR + self.gatewayName )
            event.dict['data'] = data
            event.dict['last'] = last
            self.gateway.eventEngine.put(event)
        else:
            logContent = u'合约投资者回报，错误代码：' + unicode(error['ErrorID']) + u',' + u'错误信息：' + error['ErrorMsg'].decode('gbk')
            self.gateway.onLog(logContent, level = logging.DEBUG)
    
    #----------------------------------------------------------------------
    def onRspQryTradingCode(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryInstrumentMarginRate(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryInstrumentCommissionRate(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryExchange(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryProduct(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryInstrument(self, data, error, n, last):
        """合约查询回报"""
        if error['ErrorID'] == 0:
            event = Event(type=EVENT_QRYINSTRUMENT + self.gatewayName )
            event.dict['data'] = data
            event.dict['last'] = last
            self.gateway.eventEngine.put(event)
        else:
            logContent = u'交易错误回报，错误代码：' + unicode(error['ErrorID']) + u',' + u'错误信息：' + error['ErrorMsg'].decode('gbk')
            self.gateway.onLog(logContent, level = logging.DEBUG)
    
    #----------------------------------------------------------------------
    def onRspQryDepthMarketData(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQrySettlementInfo(self, data, error, n, last):
        """查询结算信息回报"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryTransferBank(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryInvestorPositionDetail(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryNotice(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQrySettlementInfoConfirm(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryInvestorPositionCombineDetail(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryCFMMCTradingAccountKey(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryEWarrantOffset(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryInvestorProductGroupMargin(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryExchangeMarginRate(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryExchangeMarginRateAdjust(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryExchangeRate(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQrySecAgentACIDMap(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryOptionInstrTradeCost(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryOptionInstrCommRate(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryExecOrder(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryForQuote(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryQuote(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryTransferSerial(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryAccountregister(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspError(self, error, n, last):
        """错误回报"""
        err = VtErrorData()
        err.gatewayName = self.gatewayName
        err.errorID = error['ErrorID']
        err.errorMsg = error['ErrorMsg'].decode('gbk')
        self.gateway.onError(err)
    
    #----------------------------------------------------------------------
    def onRtnInstrumentStatus(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnTradingNotice(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnErrorConditionalOrder(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnExecOrder(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onErrRtnExecOrderInsert(self, data, error):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onErrRtnExecOrderAction(self, data, error):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onErrRtnForQuoteInsert(self, data, error):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnQuote(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onErrRtnQuoteInsert(self, data, error):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onErrRtnQuoteAction(self, data, error):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnForQuoteRsp(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryContractBank(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryParkedOrder(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryParkedOrderAction(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryTradingNotice(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryBrokerTradingParams(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQryBrokerTradingAlgos(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnFromBankToFutureByBank(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnFromFutureToBankByBank(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnRepealFromBankToFutureByBank(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnRepealFromFutureToBankByBank(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnFromBankToFutureByFuture(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnFromFutureToBankByFuture(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnRepealFromBankToFutureByFutureManual(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnRepealFromFutureToBankByFutureManual(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnQueryBankBalanceByFuture(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onErrRtnBankToFutureByFuture(self, data, error):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onErrRtnFutureToBankByFuture(self, data, error):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onErrRtnRepealBankToFutureByFutureManual(self, data, error):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onErrRtnRepealFutureToBankByFutureManual(self, data, error):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onErrRtnQueryBankBalanceByFuture(self, data, error):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnRepealFromBankToFutureByFuture(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnRepealFromFutureToBankByFuture(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspFromBankToFutureByFuture(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspFromFutureToBankByFuture(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRspQueryBankAccountMoneyByFuture(self, data, error, n, last):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnOpenAccountByBank(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnCancelAccountByBank(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def onRtnChangeAccountByBank(self, data):
        """"""
        pass
    
    #----------------------------------------------------------------------
    def connect(self, userID, password, brokerID, address):
        """初始化连接"""
        self.userID = userID                # 账号
        self.password = password            # 密码
        self.brokerID = brokerID            # 经纪商代码
        self.address = address              # 服务器地址
        
        # 如果尚未建立服务器连接，则进行连接
        if not self.connectionStatus:
            # 创建C++环境中的API对象，这里传入的参数是需要用来保存.con文件的文件夹路径
            path = self.gateway.file_prefix + 'tmp' + os.path.sep
            if not os.path.exists(path):
                os.makedirs(path)
            self.createFtdcTraderApi(str(path))
            
            # 注册服务器地址
            self.registerFront(self.address)
            
            # 初始化连接，成功会调用onFrontConnected
            self.init()
            
        # 若已经连接但尚未登录，则进行登录
        else:
            if not self.loginStatus:
                self.login()    
    
    #----------------------------------------------------------------------
    def login(self):
        """连接服务器"""
        # 如果填入了用户名密码等，则登录
        if self.userID and self.password and self.brokerID:
            req = {}
            req['UserID'] = self.userID
            req['Password'] = self.password
            req['BrokerID'] = self.brokerID
            self.reqID += 1
            self.reqUserLogin(req, self.reqID)   
        
    #----------------------------------------------------------------------
    def qryOrder(self):
        self.reqID += 1
        req = {}
        req['BrokerID'] = self.brokerID
        req['InvestorID'] = self.userID
        self.reqQryOrder(req, self.reqID)

    #----------------------------------------------------------------------
    def qryTrade(self):
        self.reqID += 1
        req = {}
        req['BrokerID'] = self.brokerID
        req['InvestorID'] = self.userID
        self.reqQryTrade(req, self.reqID)

    #----------------------------------------------------------------------
    def qryAccount(self):
        """查询账户"""
        self.reqID += 1
        self.reqQryTradingAccount({}, self.reqID)
        
    #----------------------------------------------------------------------
    def qryPosition(self):
        """查询持仓"""
        self.reqID += 1
        req = {}
        req['BrokerID'] = self.brokerID
        req['InvestorID'] = self.userID
        self.reqQryInvestorPosition(req, self.reqID)
    
    #----------------------------------------------------------------------
    def qryInstrument(self):
        self.reqID += 1
        req = {}
        self.reqQryInstrument(req, self.reqID)

    #----------------------------------------------------------------------
    def sendOrder(self, iorder):
        """发单"""
        self.reqID += 1
        self.orderRef = max(self.orderRef, iorder.local_id)
        req = {}
        req['InstrumentID'] = iorder.instrument.name
        req['LimitPrice'] = iorder.limit_price
        req['VolumeTotalOriginal'] = iorder.volume
        
        # 下面如果由于传入的类型本接口不支持，则会返回空字符串
        try:
            req['OrderPriceType'] = iorder.price_type
            req['Direction'] = iorder.direction
            req['CombOffsetFlag'] = iorder.action_type
        except KeyError:
            return ''
            
        req['OrderRef'] = str(iorder.local_id)
        req['InvestorID'] = self.userID
        req['UserID'] = self.userID
        req['BrokerID'] = self.brokerID
        req['CombHedgeFlag'] = defineDict['THOST_FTDC_HF_Speculation']       # 投机单
        req['ContingentCondition'] = defineDict['THOST_FTDC_CC_Immediately'] # 立即发单
        req['ForceCloseReason'] = defineDict['THOST_FTDC_FCC_NotForceClose'] # 非强平
        req['IsAutoSuspend'] = 0                                             # 非自动挂起
        req['TimeCondition'] = defineDict['THOST_FTDC_TC_GFD']               # 今日有效
        req['VolumeCondition'] = defineDict['THOST_FTDC_VC_AV']              # 任意成交量
        req['MinVolume'] = 1                                                 # 最小成交量为1       

        self.reqOrderInsert(req, self.reqID)
    
    #----------------------------------------------------------------------
    def cancelOrder(self, iorder):
        """撤单"""
        inst = iorder.instrument
        self.reqID += 1
        req = {}
        req['InstrumentID'] = iorder.instID
        req['ExchangeID'] = inst.exchange
        req['ActionFlag'] = defineDict['THOST_FTDC_AF_Delete']
        req['BrokerID'] = self.brokerID
        req['InvestorID'] = self.userID

        if len(iorder.sys_id) >0:
            req['OrderSysID'] = iorder.sys_id
        else:
            req['OrderRef'] = str(iorder.local_id)
            req['FrontID'] = self.frontID
            req['SessionID'] = self.sessionID

        self.reqOrderAction(req, self.reqID)
        
    #----------------------------------------------------------------------
    def close(self):
        """关闭"""
        self.exit()

if __name__ == '__main__':
    test()
    
