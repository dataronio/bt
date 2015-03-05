"""
Contains the core building blocks of the framework.
"""
import math
from copy import deepcopy

import pandas as pd
import numpy as np
import cython as cy


class Node(object):

    """
    The Node is the main building block in bt's tree structure design.
    Both StrategyBase and SecurityBase inherit Node. It contains the
    core functionality of a tree node.

    Args:
        * name (str): The Node name
        * parent (Node): The parent Node
        * children (dict, list): A collection of children. If dict,
            the format is {name: child}, if list then list of children.

    Attributes:
        * name (str): Node name
        * parent (Node): Node parent
        * root (Node): Root node of the tree (topmost node)
        * children (dict): Node's children
        * now (datetime): Used when backtesting to store current date
        * stale (bool): Flag used to determine if Node is stale and need
            updating
        * prices (TimeSeries): Prices of the Node. Prices for a security will
            be the security's price, for a strategy it will be an index that
            reflects the value of the strategy over time.
        * price (float): last price
        * value (float): last value
        * weight (float): weight in parent
        * full_name (str): Name including parents' names
        * members (list): Current Node + node's children

    """

    _price = cy.declare(cy.double)
    _value = cy.declare(cy.double)
    _weight = cy.declare(cy.double)
    _issec = cy.declare(cy.bint)
    _has_strat_children = cy.declare(cy.bint)

    def __init__(self, name, parent=None, children=None):

        self.name = name

        # strategy children helpers
        self._has_strat_children = False
        self._strat_children = []

        # if children is not None, we assume that we want to limit the
        # available children space to the provided list.
        if children is not None:
            if isinstance(children, list):
                # if all strings - just save as universe_filter
                if all(isinstance(x, str) for x in children):
                    self._universe_tickers = children
                    # empty dict - don't want to uselessly create
                    # tons of children when they might not be needed
                    children = {}
                else:
                    # this will be case if we pass in children
                    # (say a bunch of sub-strategies)
                    tmp = {}
                    ut = []
                    for c in children:
                        if type(c) == str:
                            tmp[c] = SecurityBase(c)
                            ut.append(c)
                        else:
                            tmp[c.name] = c

                            # if strategy, turn on flag and add name to list
                            # strategy children have special treatment
                            if isinstance(c, StrategyBase):
                                self._has_strat_children = True
                                self._strat_children.append(c.name)
                            # if not strategy, then we will want to add this to
                            # universe_tickers to filter on setup
                            else:
                                ut.append(c.name)

                    children = tmp
                    # we want to keep whole universe in this case
                    # so set to None
                    self._universe_tickers = ut

        if parent is None:
            self.parent = self
            self.root = self
        else:
            self.parent = parent
            self.root = parent.root
            parent._add_child(self)

        # default children
        if children is None:
            children = {}
            self._universe_tickers = None
        self.children = children

        self._childrenv = children.values()
        for c in self._childrenv:
            c.parent = self
            c.root = self.root

        # set default value for now
        self.now = 0
        # make sure root has stale flag
        # used to avoid unncessary update
        # sometimes we change values in the tree and we know that we will need
        # to update if another node tries to access a given value (say weight).
        # This avoid calling the update until it is actually needed.
        self.root.stale = False

        # helper vars
        self._price = 0
        self._value = 0
        self._weight = 0

        # is security flag - used to avoid updating 0 pos securities
        self._issec = False

    def __getitem__(self, key):
        return self.children[key]

    @property
    def prices(self):
        """
        A TimeSeries of the Node's price.
        """
        # can optimize depending on type -
        # securities don't need to check stale to
        # return latest prices, whereas strategies do...
        raise NotImplementedError()

    @property
    def price(self):
        """
        Current price of the Node
        """
        # can optimize depending on type -
        # securities don't need to check stale to
        # return latest prices, whereas strategies do...
        raise NotImplementedError()

    @property
    def value(self):
        """
        Current value of the Node
        """
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._value

    @property
    def weight(self):
        """
        Current weight of the Node (with respect to the parent).
        """
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._weight

    def setup(self, dates):
        """
        Setup method used to initialize a Node with a set of dates.
        """
        raise NotImplementedError()

    def _add_child(self, child):
        child.parent = self
        child.root = self.root
        if self.children is None:
            self.children = {child.name: child}
        else:
            self.children[child.name] = child

        self._childrenv = self.children.values()

    def update(self, date, data=None):
        """
        Update Node with latest date, and optionally some data.
        """
        raise NotImplementedError()

    def adjust(self, amount, update=True, isflow=True):
        """
        Adjust Node value by amount.
        """
        raise NotImplementedError()

    def allocate(self, amount, update=True):
        """
        Allocate capital to Node.
        """
        raise NotImplementedError()

    @property
    def members(self):
        """
        Node members. Members include current node as well as Node's
        children.
        """
        res = [self]
        for c in self.children.values():
            res.extend(c.members)
        return res

    @property
    def full_name(self):
        if self.parent == self:
            return self.name
        else:
            return '%s>%s' % (self.parent.full_name, self.name)


class StrategyBase(Node):

    """
    Strategy Node. Used to define strategy logic within a tree.
    A Strategy's role is to allocate capital to it's children
    based on a function.

    Args:
        * name (str): Strategy name
        * children (dict, list): A collection of children. If dict,
            the format is {name: child}, if list then list of children.
            Children can be any type of Node.
        * parent (Node): The parent Node

    Attributes:
        * name (str): Strategy name
        * parent (Strategy): Strategy parent
        * root (Strategy): Root node of the tree (topmost node)
        * children (dict): Strategy's children
        * now (datetime): Used when backtesting to store current date
        * stale (bool): Flag used to determine if Strategy is stale and need
            updating
        * prices (TimeSeries): Prices of the Strategy - basically an index that
            reflects the value of the strategy over time.
        * price (float): last price
        * value (float): last value
        * weight (float): weight in parent
        * full_name (str): Name including parents' names
        * members (list): Current Strategy + strategy's children
        * commission_fn (fn(quantity, price)): A function used to determine the
            commission (transaction fee) amount. Could be used to model slippage
            (implementation shortfall). Note that often fees are symmetric for buy
            and sell and absolute value of quantity should be used for calculation.
        * capital (float): Capital amount in Strategy - cash
        * universe (DataFrame): Data universe available at the current time.
            Universe contains the data passed in when creating a Backtest. Use
            this data to determine strategy logic.

    """

    _capital = cy.declare(cy.double)
    _net_flows = cy.declare(cy.double)
    _last_value = cy.declare(cy.double)
    _last_price = cy.declare(cy.double)
    _last_fee = cy.declare(cy.double)
    _paper_trade = cy.declare(cy.bint)

    def __init__(self, name, children=None, parent=None):
        Node.__init__(self, name, children=children, parent=parent)
        self._capital = 0
        self._weight = 1
        self._value = 0
        self._price = 100

        # helper vars
        self._net_flows = 0
        self._last_value = 0
        self._last_price = 100
        self._last_fee = 0

        # default commission function
        self.commission_fn = self._dflt_comm_fn

        self._paper_trade = False
        self._positions = None

    @property
    def price(self):
        """
        Current price.
        """
        if self.root.stale:
            self.root.update(self.now, None)
        return self._price

    @property
    def prices(self):
        """
        TimeSeries of prices.
        """
        if self.root.stale:
            self.root.update(self.now, None)
        return self._prices.ix[:self.now]

    @property
    def values(self):
        """
        TimeSeries of values.
        """
        if self.root.stale:
            self.root.update(self.now, None)
        return self._values.ix[:self.now]

    @property
    def capital(self):
        """
        Current capital - amount of unallocated capital left in strategy.
        """
        # no stale check needed
        return self._capital

    @property
    def cash(self):
        """
        TimeSeries of unallocated capital.
        """
        # no stale check needed
        return self._cash

    @property
    def fees(self):
        """
        TimeSeries of fees.
        """
        # no stale check needed
        return self._fees

    @property
    def universe(self):
        """
        Data universe available at the current time.
        Universe contains the data passed in when creating a Backtest.
        Use this data to determine strategy logic.
        """
        # avoid windowing every time
        # if calling and on same date return
        # cached value
        if self.now == self._last_chk:
            return self._funiverse
        else:
            self._last_chk = self.now
            self._funiverse = self._universe.ix[:self.now]
            return self._funiverse

    @property
    def positions(self):
        """
        TimeSeries of positions.
        """
        # if accessing and stale - update first
        if self.root.stale:
            self.root.update(self.root.now, None)

        if self._positions is not None:
            return self._positions
        else:
            vals = pd.DataFrame({x.name: x.positions for x in self.members
                                 if isinstance(x, SecurityBase)})
            self._positions = vals
            return vals

    def setup(self, universe):
        """
        Setup strategy with universe. This will speed up future calculations
        and updates.
        """
        # save full universe in case we need it
        self._original_data = universe

        # determine if needs paper trading
        # and setup if so
        if self is not self.parent:
            self._paper_trade = True
            self._paper_amount = 1000000

            paper = deepcopy(self)
            paper.parent = paper
            paper.root = paper
            paper._paper_trade = False
            paper.setup(self._original_data)
            paper.adjust(self._paper_amount)
            self._paper = paper

        # setup universe
        funiverse = universe

        if self._universe_tickers is not None:
            # if we have universe_tickers defined, limit universe to
            # those tickers
            valid_filter = list(set(universe.columns)
                                .intersection(self._universe_tickers))

            funiverse = universe[valid_filter]

            # if we have strat children, we will need to create their columns
            # in the new universe
            if self._has_strat_children:
                for c in self._strat_children:
                    funiverse[c] = np.nan

            # must create to avoid pandas warning
            funiverse = pd.DataFrame(funiverse)

        self._universe = funiverse
        # holds filtered universe
        self._funiverse = funiverse
        self._last_chk = None

        # setup internal data
        self.data = pd.DataFrame(index=funiverse.index,
                                 columns=['price', 'value', 'cash', 'fees'],
                                 data=0.0)

        self._prices = self.data['price']
        self._values = self.data['value']
        self._cash = self.data['cash']
        self._fees = self.data['fees']

        # setup children as well - use original universe here - don't want to
        # pollute with potential strategy children in funiverse
        if self.children is not None:
            [c.setup(universe) for c in self._childrenv]

    @cy.locals(newpt=cy.bint, val=cy.double, ret=cy.double)
    def update(self, date, data=None):
        """
        Update strategy. Updates prices, values, weight, etc.
        """
        # resolve stale state
        self.root.stale = False

        # update helpers on date change
        # also set newpt flag
        newpt = False
        if self.now == 0:
            newpt = True
        elif date != self.now:
            self._net_flows = 0
            self._last_price = self._price
            self._last_value = self._value
            self._last_fee = 0.0
            newpt = True

        # update now
        self.now = date

        # update children if any and calculate value
        val = self._capital  # default if no children

        if self.children is not None:
            for c in self._childrenv:
                # avoid useless update call
                if c._issec and not c._needupdate:
                    continue
                c.update(date, data)
                val += c.value

        if self.root == self:
            if val < 0:
                raise ValueError('negative root node value!')

        # update data if this value is different or
        # if now has changed - avoid all this if not since it
        # won't change
        if newpt or self._value != val:
            self._value = val
            self._values[date] = val

            try:
                ret = self._value / (self._last_value
                                     + self._net_flows) - 1
            except ZeroDivisionError:
                if self._value == 0:
                    ret = 0
                else:
                    raise ZeroDivisionError(
                        'Could not update %s. Last value '
                        'was %s and net flows were %s. Current'
                        'value is %s. Therefore, '
                        'we are dividing by zero to obtain the return '
                        'for the period.' % (self.name,
                                             self._last_value,
                                             self._net_flows,
                                             self._value))

            self._price = self._last_price * (1 + ret)
            self._prices[date] = self._price

        # update children weights
        if self.children is not None:
            for c in self._childrenv:
                # avoid useless update call
                if c._issec and not c._needupdate:
                    continue
                try:
                    c._weight = c.value / val
                except ZeroDivisionError:
                    c._weight = 0.0

        # if we have strategy children, we will need to update them in universe
        if self._has_strat_children:
            for c in self._strat_children:
                self._universe.loc[date, c] = self.children[c].price

        # Cash should track the unallocated capital at the end of the day, so
        # we should update it every time we call "update".
        # Same for fess
        self._cash[self.now] = self._capital
        self._fees[self.now] = self._last_fee

        # update paper trade if necessary
        if newpt and self._paper_trade:
            self._paper.update(date)
            self._paper.run()
            self._paper.update(date)
            # update price
            self._price = self._paper.price
            self._prices[date] = self._price

    @cy.locals(amount=cy.double, update=cy.bint, flow=cy.bint, fees=cy.double)
    def adjust(self, amount, update=True, flow=True, fee=0.0):
        """
        Adjust capital - used to inject capital to a Strategy. This injection
        of capital will have no effect on the children.

        Args:
            * amount (float): Amount to adjust by.
            * update (bool): Force update?
            * flow (bool): Is this adjustment a flow? Basically a flow will
                have an impact on the price index. Examples of flows are
                commissions.

        """
        # adjust capital
        self._capital += amount
        self._last_fee += fee

        # if flow - increment net_flows - this will not affect
        # performance. Commissions and other fees are not flows since
        # they have a performance impact
        if flow:
            self._net_flows += amount

        if update:
            # indicates that data is now stale and must
            # be updated before access
            self.root.stale = True

    @cy.locals(amount=cy.double, update=cy.bint)
    def allocate(self, amount, child=None, update=True):
        """
        Allocate capital to Strategy. By default, capital is allocated
        recursively down the children, proportionally to the children's
        weights.  If a child is specified, capital will be allocated
        to that specific child.

        Allocation also have a side-effect. They will deduct the same amount
        from the parent's "account" to offset the allocation. If there is
        remaining capital after allocation, it will remain in Strategy.

        Args:
            * amount (float): Amount to allocate.
            * child (str): If specified, allocation will be directed to child
                only. Specified by name.
            * update (bool): Force update.

        """
        # allocate to child
        if child is not None:
            if child not in self.children:
                c = SecurityBase(child)
                c.setup(self._universe)
                # update to bring up to speed
                c.update(self.now)
                # add child to tree
                self._add_child(c)

            # allocate to child
            self.children[child].allocate(amount)
        # allocate to self
        else:
            # adjust parent's capital
            # no need to update now - avoids repetition
            if self.parent == self:
                self.parent.adjust(-amount, update=False, flow=True)
            else:
                # do NOT set as flow - parent will be another strategy
                # and therefore should not incur flow
                self.parent.adjust(-amount, update=False, flow=False)

            # adjust self's capital
            self.adjust(amount, update=False, flow=True)

            # push allocation down to children if any
            # use _weight to avoid triggering an update
            if self.children is not None:
                [c.allocate(amount * c._weight, update=False)
                 for c in self._childrenv]

            # mark as stale if update requested
            if update:
                self.root.stale = True

    @cy.locals(delta=cy.double, weight=cy.double, base=cy.double)
    def rebalance(self, weight, child, base=np.nan, update=True):
        """
        Rebalance a child to a given weight.

        This is a helper method to simplify code logic. This method is used
        when we want to se the weight of a particular child to a set amount.
        It is similar to allocate, but it calculates the appropriate allocation
        based on the current weight.

        Args:
            * weight (float): The target weight. Usually between -1.0 and 1.0.
            * child (str): child to allocate to - specified by name.
            * base (float): If specified, this is the base amount all weight
                delta calculations will be based off of. This is useful when we
                determine a set of weights and want to rebalance each child
                given these new weights. However, as we iterate through each
                child and call this method, the base (which is by default the
                current value) will change. Therefore, we can set this base to
                the original value before the iteration to ensure the proper
                allocations are made.
            * update (bool): Force update?

        """
        # if weight is 0 - we want to close child
        if weight == 0:
            if child in self.children:
                return self.close(child)
            else:
                return

        # if no base specified use self's value
        if np.isnan(base):
            base = self.value

        # else make sure we have child
        if child not in self.children:
            c = SecurityBase(child)
            c.setup(self._universe)
            # update child to bring up to speed
            c.update(self.now)
            self._add_child(c)

        # allocate to child
        # figure out weight delta
        c = self.children[child]
        delta = weight - c.weight
        c.allocate(delta * base)

    def close(self, child):
        """
        Close a child position - alias for rebalance(0, child). This will also
        flatten (close out all) the child's children.

        Args:
            * child (str): Child, specified by name.
        """
        c = self.children[child]
        # flatten if children not None
        if c.children is not None and len(c.children) != 0:
            c.flatten()
        c.allocate(-c.value)

    def flatten(self):
        """
        Close all child positions.
        """
        # go right to base alloc
        [c.allocate(-c.value) for c in self._childrenv if c.value != 0]

    def run(self):
        """
        This is the main logic method. Override this method to provide some
        algorithm to execute on each date change. This method is called by
        backtester.
        """
        pass

    def set_commissions(self, fn):
        """
        Set commission (transaction fee) function.

        Args:
            fn (fn(quantity, price)): Function used to determine commission amount.

        """
        self.commission_fn = fn

    @cy.locals(q=cy.double, p=cy.double)
    def _dflt_comm_fn(self, q, p):
        return max(1, abs(q) * 0.01)


class SecurityBase(Node):

    """
    Security Node. Used to define a security within a tree.
    A Security's has no children. It simply models an asset that can be bought
    or sold.

    Args:
        * name (str): Security name
        * multiplier (float): security multiplier - typically used for
            derivatives.

    Attributes:
        * name (str): Security name
        * parent (Security): Security parent
        * root (Security): Root node of the tree (topmost node)
        * now (datetime): Used when backtesting to store current date
        * stale (bool): Flag used to determine if Security is stale and need
            updating
        * prices (TimeSeries): Security prices.
        * price (float): last price
        * value (float): last value - basically position * price * multiplier
        * weight (float): weight in parent
        * full_name (str): Name including parents' names
        * members (list): Current Security + strategy's children
        * position (float): Current position (quantity).

    """

    _last_pos = cy.declare(cy.double)
    _position = cy.declare(cy.double)
    multiplier = cy.declare(cy.double)
    _prices_set = cy.declare(cy.bint)
    _needupdate = cy.declare(cy.bint)

    @cy.locals(multiplier=cy.double)
    def __init__(self, name, multiplier=1):
        Node.__init__(self, name, parent=None, children=None)
        self._value = 0
        self._price = 0
        self._weight = 0
        self._position = 0
        self.multiplier = multiplier

        # opt
        self._last_pos = 0
        self._issec = True
        self._needupdate = True

    @property
    def price(self):
        """
        Current price.
        """
        # if accessing and stale - update first
        if self._needupdate:
            self.update(self.root.now)
        return self._price

    @property
    def prices(self):
        """
        TimeSeries of prices.
        """
        # if accessing and stale - update first
        if self._needupdate:
            self.update(self.root.now)
        return self._prices.ix[:self.now]

    @property
    def values(self):
        """
        TimeSeries of values.
        """
        # if accessing and stale - update first
        if self._needupdate:
            self.update(self.root.now)
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._values.ix[:self.now]

    @property
    def position(self):
        """
        Current position
        """
        # no stale check needed
        return self._position

    @property
    def positions(self):
        """
        TimeSeries of positions.
        """
        # if accessing and stale - update first
        if self._needupdate:
            self.update(self.root.now)
        if self.root.stale:
            self.root.update(self.root.now, None)
        return self._positions.ix[:self.now]

    def setup(self, universe):
        """
        Setup Security with universe. Speeds up future runs.

        Args:
            * universe (DataFrame): DataFrame of prices with security's name as
                one of the columns.

        """
        # if we already have all the prices, we will store them to speed up
        # future udpates
        try:
            prices = universe[self.name]
        except KeyError:
            prices = None

        # setup internal data
        if prices is not None:
            self._prices = prices
            self.data = pd.DataFrame(index=universe.index,
                                     columns=['value', 'position'],
                                     data=0.0)
            self._prices_set = True
        else:
            self.data = pd.DataFrame(index=universe.index,
                                     columns=['price', 'value', 'position'])
            self._prices = self.data['price']
            self._prices_set = False

        self._values = self.data['value']
        self._positions = self.data['position']

    @cy.locals(prc=cy.double)
    def update(self, date, data=None):
        """
        Update security with a given date and optionally, some data.
        This will update price, value, weight, etc.
        """
        # filter for internal calls when position has not changed - nothing to
        # do. Internal calls (stale root calls) have None data. Also want to
        # make sure date has not changed, because then we do indeed want to
        # update.
        if date == self.now and self._last_pos == self._position:
            return

        # date change - update price
        if date != self.now:
            # update now
            self.now = date

            if self._prices_set:
                self._price = self._prices[self.now]
            # traditional data update
            elif data is not None:
                prc = data[self.name]
                self._price = prc
                self._prices[date] = prc

        self._positions[date] = self._position
        self._last_pos = self._position

        self._value = self._position * self._price * self.multiplier
        self._values[date] = self._value

        if self._weight == 0 and self._position == 0:
            self._needupdate = False

    @cy.locals(amount=cy.double, update=cy.bint, q=cy.double, outlay=cy.double)
    def allocate(self, amount, update=True):
        """
        This allocates capital to the Security. This is the method used to
        buy/sell the security.

        A given amount of shares will be determined on the current price, a
        commisison will be calculated based on the parent's commission fn, and
        any remaining capital will be passed back up  to parent as an
        adjustment.

        Args:
            * amount (float): Amount of adjustment.
            * update (bool): Force update?

        """

        # will need to update if this has been idle for a while...
        # update if needupdate or if now is stale
        # fetch parent's now since our now is stale
        if self._needupdate or self.now != self.parent.now:
            self.update(self.parent.now)

        # ignore 0 alloc
        # Note that if the price of security has dropped to zero, then it should
        # never be selected by SelectAll, SelectN etc. I.e. we should not open the
        # position at zero price. At the same time, we are able to close it at zero
        # price, because at that point amount=0.
        if amount == 0:
            return

        if self.parent is self or self.parent is None:
            raise Exception(
                'Cannot allocate capital to a parentless security')

        if self._price == 0 or np.isnan(self._price):
            raise Exception(
                'Cannot allocate capital to '
                '%s because price is 0 or nan as of %s'
                % (self.name, self.parent.now))

        # buy/sell
        # determine quantity - must also factor in commission
        # closing out?
        if amount == -self._value:
            q = -self._position
        else:
            if (self._position > 0) or ((self._position == 0) and (amount > 0)):
                # if we're going long or changing long position
                q = math.floor(amount / (self._price * self.multiplier))
            else:
                # if we're going short or changing short position
                q = math.ceil(amount / (self._price * self.multiplier))

        # if q is 0 nothing to do
        if q == 0 or np.isnan(q):
            return

        # this security will need an update, even if pos is 0 (for example if
        # we close the positions, value and pos is 0, but still need to do that
        # last update)
        self._needupdate = True

        # adjust position & value
        self._position += q

        # calculate proper adjustment for parent
        # parent passed down amount so we want to pass
        # -outlay back up to parent to adjust for capital
        # used
        outlay, fee = self.outlay(q)

        # call parent
        self.parent.adjust(-outlay, update=update, flow=False, fee=fee)

    @cy.locals(q=cy.double, p=cy.double)
    def commission(self, q, p):
        """
        Calculates the commission (transaction fee) based on quantity and price.
        Uses the parent's commission_fn.

        Args:
            * q (float): quantity
            * p (float): price

        """
        return self.parent.commission_fn(q, p)

    @cy.locals(q=cy.double)
    def outlay(self, q):
        """
        Determines the complete cash outlay (including commission) necessary
        given a quantity q.
        Second returning parameter is a commission itself.

        Args:
            * q (float): quantity

        """
        fee = self.commission(q, self._price * self.multiplier)
        full_outlay = q * self._price * self.multiplier + fee
        return full_outlay, fee

    def run(self):
        """
        Does nothing - securities have nothing to do on run.
        """
        pass


class Algo(object):

    """
    Algos are used to modularize strategy logic so that strategy logic becomes
    modular, composable, more testable and less error prone. Basically, the
    Algo should follow the unix philosophy - do one thing well.

    In practice, algos are simply a function that receives one argument, the
    Strategy (refered to as target) and are expected to return a bool.

    When some state preservation is necessary between calls, the Algo
    object can be used (this object). The __call___ method should be
    implemented and logic defined therein to mimic a function call. A
    simple function may also be used if no state preservation is neceesary.

    Args:
        * name (str): Algo name

    """

    def __init__(self, name=None):
        self._name = name

    @property
    def name(self):
        """
        Algo name.
        """
        if self._name is None:
            self._name = self.__class__.__name__
        return self._name

    def __call__(self, target):
        raise NotImplementedError("%s not implemented!" % self.name)


class AlgoStack(Algo):

    """
    An AlgoStack derives from Algo runs multiple Algos until a
    failure is encountered.

    The purpose of an AlgoStack is to group a logic set of Algos together. Each
    Algo in the stack is run. Execution stops if one Algo returns False.

    Args:
        * algos (list): List of algos.

    """

    def __init__(self, *algos):
        super(AlgoStack, self).__init__()
        self.algos = algos
        self.check_run_always = any(hasattr(x, 'run_always')
                                    for x in self.algos)

    def __call__(self, target):
        # normal runing mode
        if not self.check_run_always:
            for algo in self.algos:
                if not algo(target):
                    return False
            return True
        # run mode when at least one algo has a run_always attribute
        else:
            # store result in res
            # allows continuation to check for and run
            # algos that have run_always set to True
            res = True
            for algo in self.algos:
                if res:
                    res = algo(target)
                elif hasattr(algo, 'run_always'):
                    if algo.run_always:
                        algo(target)
            return res


class Strategy(StrategyBase):

    """
    Strategy expands on the StrategyBase and incorporates Algos.

    Basically, a Strategy is built by passing in a set of algos. These algos
    will be placed in an Algo stack and the run function will call the stack.

    Furthermore, two class attributes are created to pass data between algos.
    perm for permanent data, temp for temporary data.

    Args:
        * name (str): Strategy name
        * algos (list): List of Algos to be passed into an AlgoStack
        * children (dict, list): Children - useful when you want to create
            strategies of strategies

    Attributes:
        * stack (AlgoStack): The stack
        * temp (dict): A dict containing temporary data - cleared on each call
            to run. This can be used to pass info to other algos.
        * perm (dict): Permanent data used to pass info from one algo to
            another. Not cleared on each pass.

    """

    def __init__(self, name, algos=[], children=None):
        super(Strategy, self).__init__(name, children=children)
        self.stack = AlgoStack(*algos)
        self.temp = {}
        self.perm = {}

    def run(self):
        # clear out temp data
        self.temp = {}

        # run algo stack
        self.stack(self)

        # run children
        for c in self.children.values():
            c.run()
