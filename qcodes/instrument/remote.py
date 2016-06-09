"""Proxies to interact with server-based instruments from another process."""
import multiprocessing as mp

from qcodes.utils.deferred_operations import DeferredOperations
from qcodes.utils.helpers import DelegateAttributes, named_repr
from .parameter import Parameter, GetLatest
from .function import Function
from .server import get_instrument_server_manager


class RemoteInstrument(DelegateAttributes):

    """
    A proxy for an instrument (of any class) running on a server process.

    Creates the server if necessary, then loads this instrument onto it,
    then mirrors the API to that instrument.

    Args:
        *args: Passed along to the real instrument constructor.

        instrument_class (type): The class of the real instrument to make.

        server_name (str): The name of the server to create or use for this
            instrument. If not provided (''), gets a name from
            ``instrument_class.default_server_name(**kwargs)`` using the
            same kwargs passed to the instrument constructor.

        **kwargs: Passed along to the real instrument constructor, also
            to ``default_server_name`` as mentioned.
    """

    delegate_attr_dicts = ['_methods', 'parameters', 'functions']

    def __init__(self, *args, instrument_class=None, server_name='',
                 **kwargs):

        if server_name == '':
            server_name = instrument_class.default_server_name(**kwargs)

        shared_kwargs = {}
        for kwname in instrument_class.shared_kwargs:
            if kwname in kwargs:
                shared_kwargs[kwname] = kwargs[kwname]
                del kwargs[kwname]

        self._server_name = server_name
        self._shared_kwargs = shared_kwargs
        self._manager = get_instrument_server_manager(self._server_name,
                                                      self._shared_kwargs)

        self._instrument_class = instrument_class
        self._args = args
        self._kwargs = kwargs

        instrument_class.record_instance(self)
        self.connect()

    def connect(self):
        """Create the instrument on the server and replicate its API here."""
        connection_attrs = self._manager.connect(self, self._instrument_class,
                                                 self._args, self._kwargs)

        self.name = connection_attrs['name']
        self._id = connection_attrs['id']

        # bind all the different categories of actions we need
        # to interface with the remote instrument

        self._methods = {
            name: RemoteMethod(name, self, attrs)
            for name, attrs in connection_attrs['methods'].items()
        }

        self.parameters = {
            name: RemoteParameter(name, self, attrs)
            for name, attrs in connection_attrs['parameters'].items()
        }

        self.functions = {
            name: RemoteFunction(name, self, attrs)
            for name, attrs in connection_attrs['functions'].items()
        }

    def _ask_server(self, func_name, *args, **kwargs):
        """Query the server copy of this instrument, expecting a response."""
        return self._manager.ask('cmd', self._id, func_name, *args, **kwargs)

    def _write_server(self, func_name, *args, **kwargs):
        """Send a command to the server, without waiting for a response."""
        self._manager.write('cmd', self._id, func_name, *args, **kwargs)

    def add_parameter(self, name, **kwargs):
        """
        Proxy to add a new parameter to the server instrument.

        Also replicates its API here.

        Adding parameters when the instrument is already on the server is
        limited in that you can generally only use the string form of a
        command, not the callable form.
        """
        attrs = self._ask_server('add_parameter', name, **kwargs)
        self.parameters[name] = RemoteParameter(name, self, attrs)

    def add_function(self, name, **kwargs):
        """
        Proxy to add a new function to the server instrument.

        Also replicates its API here.

        Adding functions when the instrument is already on the server is
        limited in that you can generally only use the string form of a
        command, not the callable form.
        """
        attrs = self._ask_server('add_function', name, **kwargs)
        self.functions[name] = RemoteFunction(name, self, attrs)

    def instances(self):
        """A RemoteInstrument shows as an instance of its proxied class."""
        return self._instrument_class.instances()

    def close(self):
        """Irreversibly close and tear down the server & remote instruments."""
        if hasattr(self, '_manager'):
            if self._manager._server in mp.active_children():
                self._manager.delete(self._id)
            del self._manager
        self._instrument_class.remove_instance(self)

    def restart(self):
        """Remove and recreate the server copy of this instrument."""
        # TODO - this cannot work! _manager is gone after close!
        self.close()
        self._manager.restart()

    def __getitem__(self, key):
        """Delegate instrument['name'] to parameter or function 'name'."""
        try:
            return self.parameters[key]
        except KeyError:
            return self.functions[key]

    def __repr__(self):
        """repr including the instrument name."""
        return named_repr(self)


class RemoteComponent:

    """
    An object that lives inside a RemoteInstrument.

    Proxies all of its calls to the corresponding object in the server
    instrument.

    Args:
        name (str): the name of this component
        instrument (RemoteInstrument): the instrument this is part of.
        attrs (dict): instance attributes to set, to match the server
            copy of this component.
    """

    def __init__(self, name, instrument, attrs):
        self.name = name
        self._instrument = instrument

        for attribute, value in attrs.items():
            if attribute == '__doc__' and value:
                value = '{} {} in RemoteInstrument {}\n---\n\n{}'.format(
                    type(self).__name__, self.name, instrument.name, value)
            setattr(self, attribute, value)

    def __repr__(self):
        """repr including the component name."""
        return named_repr(self)


class RemoteMethod(RemoteComponent):

    """Proxy for a method of the server instrument."""

    def __call__(self, *args, **kwargs):
        """Call the method on the server, passing on any args and kwargs."""
        return self._instrument._ask_server(self.name, *args, **kwargs)


class RemoteParameter(RemoteComponent, DeferredOperations):

    """Proxy for a Parameter of the server instrument."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.get_latest = GetLatest(self)

    def __call__(self, *args):
        """Shortcut to get (with no args) or set (with one arg)."""
        if len(args) == 0:
            return self.get()
        else:
            self.set(*args)

    def get(self):
        """Read the value of this parameter."""
        return self._instrument._ask_server('get', self.name)

    def set(self, value):
        """Set a new value of this parameter."""
        # TODO: sometimes we want set to block (as here) and sometimes
        # we want it async... which would just be changing the '_ask_server'
        # to '_write_server' below. how do we decide, and how do we let the
        # user do it?
        self._instrument._ask_server('set', self.name, value)

    # manually copy over validate and __getitem__ so they execute locally
    # no reason to send these to the server, unless the validators change...
    def validate(self, value):
        """Test if a value is allowed for this parameter."""
        return Parameter.validate(self, value)

    def __getitem__(self, keys):
        """Create a SweepValues from this parameter with slice notation."""
        return Parameter.__getitem__(self, keys)

    def sweep(self, *args, **kwargs):
        """Create a SweepValues from this parameter. See Parameter.sweep."""
        return Parameter.sweep(self, *args, **kwargs)

    def _latest(self):
        return self._instrument._ask_server('callattr', self.name + '._latest')

    def snapshot(self, update=False):
        """JSON state of this parameter."""
        return self._instrument._ask_server('callattr',
                                            self.name + '.snapshot', update)

    def setattr(self, attr, value):
        """
        Set an attribute of the parameter on the server.

        Args:
            attr (str): the attribute name. Can be nested as in
                ``NestedAttrAccess``.
            value: The new value to set.
        """
        self._instrument._ask_server('setattr', self.name + '.' + attr, value)

    def getattr(self, attr):
        """
        Get an attribute of the parameter on the server.

        Args:
            attr (str): the attribute name. Can be nested as in
                ``NestedAttrAccess``.
        """
        return self._instrument._ask_server('getattr', self.name + '.' + attr)

    def callattr(self, attr, *args, **kwargs):
        """
        Call arbitrary methods of the parameter on the server.

        Args:
            attr (str): the method name. Can be nested as in
                ``NestedAttrAccess``.
            *args: positional args to the method
            **kwargs: keyword args to the method
        """
        return self._instrument._ask_server(
            'callattr', self.name + '.' + attr, *args, **kwargs)


class RemoteFunction(RemoteComponent):

    """Proxy for a Function of the server instrument."""

    def __call__(self, *args):
        """Call the Function. Functions take only positional args."""
        return self._instrument._ask_server('call', self.name, *args)

    def call(self, *args):
        """An alias for __call__."""
        return self.__call__(*args)

    def validate(self, *args):
        """Test if these arguments are valid for this Function."""
        return Function.validate(self, *args)
