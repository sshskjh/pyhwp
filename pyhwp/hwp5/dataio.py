# -*- coding: utf-8 -*-
#
#                    GNU AFFERO GENERAL PUBLIC LICENSE
#                       Version 3, 19 November 2007
#
#    pyhwp : hwp file format parser in python
#    Copyright (C) 2010 mete0r@sarangbang.or.kr
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
import struct
import logging
from .importhelper import importStringIO
StringIO = importStringIO()

class Eof(Exception):
    def __init__(self, *args):
        self.args = args
class OutOfData(Exception):
    pass

def readn(f, size):
    data = f.read(size)
    datasize = len(data)
    if datasize == 0:
        try:
            pos = f.tell()
        except IOError:
            pos = '<UNKNOWN>'
        raise Eof(pos)
    return data

class Primitive(type):
    def read(self, f, context=None):
        return self.decode(readn(f, self.calcsize))
    def decode(self, s, context=None):
        return struct.unpack(self.fmt, s)[0]

class _new(object):
    def __init__(self, basetype):
        self.basetype = basetype
    def __call__(self, cls, *args, **kwargs):
        return self.basetype.__new__(self.basetype, *args, **kwargs)

def _Primitive(name, basetype, fmt):
    return Primitive(name, (basetype,), dict(basetype=basetype,
                                             fmt=fmt,
                                             calcsize=struct.calcsize(fmt),
                                             __new__=staticmethod(_new(basetype)),
                                             __slots__=[]))

UINT32 = _Primitive('UINT32', long, '<I')
INT32 = _Primitive('INT32', int, '<i')
UINT16 = _Primitive('UINT16', int, '<H')
INT16 = _Primitive('INT16', int, '<h')
UINT8 = _Primitive('UINT8', int, '<B')
INT8 = _Primitive('INT8', int, '<b')
WORD = _Primitive('WORD', int, '<H')
BYTE = _Primitive('BYTE', int, '<B')
DOUBLE = _Primitive('DOUBLE', float, '<d')
WCHAR = _Primitive('WCHAR', int, '<H')

def decode_utf16le_besteffort(s):
    while True:
        try:
            return s.decode('utf-16le')
        except UnicodeDecodeError, e:
            logging.error('can\'t parse (%d-%d) %s'%(e.start, e.end, hexdump(s)))
            s = s[:e.start] + '.'*(e.end-e.start) + s[e.end:]
            continue

class BSTR(unicode):
    __new__ = _new(unicode)
    def read(f, context):
        size = UINT16.read(f, None)
        if size == 0:
            return u''
        data = readn(f, 2*size)
        return decode_utf16le_besteffort(data)
    read = staticmethod(read)

inch2mm = lambda x: float(int(x * 25.4 * 100 + 0.5)) / 100
hwp2inch = lambda x: x / 7200.0
hwp2mm = lambda x: inch2mm(hwp2inch(x))
hwp2pt = lambda x: int( (x/100.0)*10 + 0.5)/10.0
HWPUNIT = _Primitive('HWPUNIT', long, '<I')
SHWPUNIT = _Primitive('SHWPUNIT', int, '<i')
HWPUNIT16 = _Primitive('HWPUNIT16', int, '<h')

class BitGroupDescriptor(object):
    def __init__(self, bitgroup):
        valuetype = int
        if isinstance(bitgroup, tuple):
            if len(bitgroup) > 2:
                lsb, msb, valuetype = bitgroup
            else:
                lsb, msb = bitgroup
        else:
            lsb = msb = bitgroup
        self.lsb = lsb
        self.msb = msb
        self.valuetype = valuetype

    def __get__(self, instance, owner):
        valuetype = self.valuetype
        lsb = self.lsb
        msb = self.msb
        return valuetype(int(instance >> lsb) & int( (2**(msb+1-lsb)) - 1))

class FlagsType(type):
    def __new__(mcs, name, bases, attrs):
        basetype = attrs.pop('basetype')
        bases = (basetype.basetype,)

        bitgroups = dict((k, BitGroupDescriptor(v)) for k, v in attrs.iteritems())

        attrs = dict(bitgroups)
        attrs['__name__'] = name
        attrs['__slots__'] = ()

        attrs['basetype'] = basetype
        attrs['bitfields'] = bitgroups

        def dictvalue(self):
            return dict((name, getattr(self, name))
                        for name in bitgroups.keys())
        attrs['dictvalue'] = dictvalue

        return type.__new__(mcs, name, bases, attrs)

    def read(cls, f, context):
        return cls(cls.basetype.read(f, context))


def _lex_flags_args(args):
    for idx, arg in enumerate(args):
        while True:
            pushback = (yield idx, arg)
            if pushback is arg:
                yield
                continue
            break


def _parse_flags_args(args):
    args = _lex_flags_args(args)
    try:
        idx = -1
        while True:
            # lsb
            try:
                idx, lsb = args.next()
            except StopIteration:
                break
            assert isinstance(lsb, int), '#%d arg is expected to be a int: %s'%(idx, repr(lsb))

            # msb (default: lsb)
            idx, x = args.next()
            if isinstance(x, int):
                msb = x
            elif isinstance(x, (type, basestring)):
                args.send(x) # pushback
                msb = lsb
            else:
                assert False, '#%d arg is unexpected type: %s'%(idx, repr(x))

            # type (default: int)
            idx, x = args.next()
            assert not isinstance(x, int), '#%d args is expected to be a type or name: %s'%(idx, repr(x))
            if isinstance(x, type):
                t = x
            elif isinstance(x, basestring):
                args.send(x) # pushback
                t = int
            else:
                assert False, '#%d arg is unexpected type: %s'%(idx, repr(x))

            # name
            idx, name = args.next()
            assert isinstance(name, basestring), '#%d args is expected to be a name: %s'%(idx, repr(name))

            yield name, (lsb, msb, t)

    except StopIteration:
        assert False, '#%d arg is expected'%(idx+1)


def Flags(basetype, *args):
    attrs = dict(_parse_flags_args(args))
    attrs['basetype'] = basetype
    return FlagsType('Flags', (), attrs)


enum_types = dict()
class EnumType(type):
    def __new__(mcs, name, bases, attrs):
        items = attrs.pop('items')
        moreitems = attrs.pop('moreitems')
        names = dict()
        registry = dict()
        for k, v in moreitems.iteritems():
            assert not k in attrs, 'name clashes: %s'%k
            attrs[k] = v
            names[v] = k
            registry[k] = v
        for v, k in enumerate(items):
            assert not k in attrs, 'name clashes: %s'%k
            attrs[k] = v
            names[v] = k
            registry[k] = v
        def repr(self):
            enum_name = type(self).__name__
            item_name = names.get(self)
            if item_name is not None:
                return enum_name+'.'+item_name
            else:
                return '%s(%d)'%(enum_name, self)
        attrs['__repr__'] = repr
        attrs['__slots__'] = []
        cls = type.__new__(mcs, name, bases, attrs)
        enum_types[cls] = dict(items=registry, value_instances=dict(), names=names)
        return cls
    def __init__(cls, name, bases, attrs):
        type.__init__(cls, name, bases, attrs)
        for k, v in enum_types[cls]['items'].iteritems():
            setattr(cls, k, cls(v))
    def __call__(cls, value):
        if isinstance(value, cls):
            return value
        value_instances = enum_types[cls]['value_instances']
        instance = super(EnumType, cls).__call__(value)
        return value_instances.setdefault(value, instance)
    def name_for(cls, value):
        return enum_types[cls]['names'].get(value, str(value))

def Enum(*items, **moreitems):
    attrs = dict(items=items, moreitems=moreitems)
    return EnumType('Enum', (int,), attrs)


class CompoundType(type):
    pass


class ArrayType(CompoundType):
    def __init__(self, *args, **kwargs):
        pass


class FixedArrayType(ArrayType):

    classes = dict()

    def __new__(mcs, itemtype, size):
        key = itemtype, size

        cls = mcs.classes.get(key)
        if cls is not None:
            return cls

        attrs = dict(itemtype=itemtype, size=size)
        name = 'ARRAY(%s,%s)' % (itemtype.__name__, size)
        cls = ArrayType.__new__(mcs, name, (tuple,), attrs)
        mcs.classes[key] = cls
        return cls

    def read(cls, f, context=None):
        result = []
        for i in range(0, cls.size):
            value = cls.itemtype.read(f, context)
            result.append( value )
        return tuple(result)


ARRAY = FixedArrayType


class VariableLengthArrayType(ArrayType):

    classes = dict()

    def __new__(mcs, counttype, itemtype):
        key = counttype, itemtype

        cls = mcs.classes.get(key)
        if cls is not None:
            return cls

        attrs = dict(itemtype=itemtype, counttype=counttype)
        name = 'N_ARRAY(%s,%s)' % (counttype.__name__, itemtype.__name__)
        cls = ArrayType.__new__(mcs, name, (list,), attrs)
        mcs.classes[key] = cls
        return cls

    def read(cls, f, context):
        result = []
        count = cls.counttype.read(f, context)
        for i in range(0, count):
            value = cls.itemtype.read(f, context)
            result.append( value )
        return result


N_ARRAY = VariableLengthArrayType


class ParseError(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, **kwargs)
        self.cause = None
        self.path = None
        self.record = None
        self.context = []


def read_struct_members(model, context, stream):
    def read_member(member):
        return read_type_value(context, member['type'], stream)
    members = model.parse_members_with_inherited(context, read_member)
    members = supplement_parse_error_with_offset(members, stream)
    members = supplement_parse_error_with_parsed(members)
    return members


def read_struct_members_defined(struct_type, stream, context):
    def read_member(member):
        return read_type_value(context, member['type'], stream)
    members = struct_type.parse_members(context, read_member)
    members = supplement_parse_error_with_offset(members, stream)
    members = supplement_parse_error_with_parsed(members)
    return members


def read_struct_members_up_to(struct_type, up_to_type, stream, context):
    stream = context['stream']
    def read_member(member):
        return read_type_value(context, member['type'], stream)
    members = struct_type.parse_members_with_inherited(context, read_member,
                                                 up_to_type)
    members = supplement_parse_error_with_offset(members, stream)
    members = supplement_parse_error_with_parsed(members)
    return members


def supplement_parse_error_with_parsed(members):
    parsed_members = list()
    try:
        for member in members:
            yield member
            parsed_members.append(member)
    except ParseError, e:
        e.context[-1]['parsed'] = parsed_members
        raise
        

def supplement_parse_error_with_offset(members, stream):
    while True:
        offset = stream.tell()
        try:
            member = members.next()
        except ParseError, e:
            e.context[-1]['offset'] = offset
            raise
        except StopIteration:
            return
        yield member


def augment_members_with_offset(members, stream):
    while True:
        offset = stream.tell()
        try:
            member = members.next()
        except StopIteration:
            return
        yield (offset, stream.tell()), member


def read_type_value(context, type, stream):
    try:
        return type.read(stream, context)
    except ParseError:
        raise
    except Exception, e:
        msg = 'can\'t parse %s' % type
        pe = ParseError(msg)
        pe.cause = e
        pe.path = context.get('path')
        pe.record = context.get('record')
        pe.offset = stream.tell()
        raise pe


def typed_struct_attributes(struct, attributes, context):
    attributes = dict(attributes)
    def popvalue(member):
        name = member['name']
        if name in attributes:
            return attributes.pop(name)
        else:
            return member['type']()

    for member in struct.parse_members_with_inherited(context, popvalue):
        yield member

    # remnants
    for name, value in attributes.iteritems():
        yield dict(name=name, type=type(value), value=value)


class StructType(CompoundType):
    def __init__(cls, name, bases, attrs):
        super(StructType, cls).__init__(name, bases, attrs)
        if 'attributes' in cls.__dict__:
            members = (dict(type=member[0], name=member[1])
                       if isinstance(member, tuple)
                       else member
                       for member in cls.attributes())
            cls.members = list(members)
        for k, v in attrs.iteritems():
            if isinstance(v, EnumType):
                v.__name__ = k
            elif isinstance(v, FlagsType):
                v.__name__ = k

    def read(cls, f, context=None):
        if context is None:
            context = dict()
        members = read_struct_members(cls, context, f)
        members = ((m['name'], m['value']) for m in members)
        return dict(members)

    def parse_members(cls, context, getvalue):
        if 'attributes' not in cls.__dict__:
            return
        values = dict()
        for member in cls.members:
            member = dict(member)
            if 'type_func' in member:
                member['type'] = member['type_func'](context, values)

            member_version = member.get('version')
            if member_version is None or context['version'] >= member_version:
                condition_func = member.get('condition')
                if condition_func is None or condition_func(context, values):
                    try:
                        value = getvalue(member)
                    except ParseError, e:
                        e.context.append(dict(model=cls, member=member['name']))
                        raise
                    values[member['name']] = member['value'] = value
                    yield member

    def parse_members_with_inherited(cls, context, getvalue, up_to_cls=None):
        import inspect
        from itertools import takewhile
        mro = inspect.getmro(cls)
        mro = takewhile(lambda cls: cls is not up_to_cls, mro)
        mro = list(cls for cls in mro if 'attributes' in cls.__dict__)
        mro = reversed(mro)
        for cls in mro:
            for member in cls.parse_members(context, getvalue):
                yield member


class Struct(object):
    __metaclass__ = StructType


def dumpbytes(data, crust=False):
    offsbase = 0
    if crust:
        yield '\t 0  1  2  3  4  5  6  7  8  9  A  B  C  D  E  F'
    while len(data) > 16:
        if crust:
            line = '%05x0: '%offsbase
        else:
            line = ''
        line += ' '.join(['%02x'%ord(ch) for ch in data[0:16]]) 
        yield line
        data = data[16:]
        offsbase += 1

    if crust:
        line = '%05x0: '%offsbase
    else:
        line = ''
    line += ' '.join(['%02x'%ord(ch) for ch in data]) 
    yield line

def hexdump(data, crust=False):
    return '\n'.join([line for line in dumpbytes(data, crust)])

class IndentedOutput:
    def __init__(self, base, level):
        self.base = base
        self.level = level
    def write(self, x):
        for line in x.split('\n'):
            if len(line) > 0:
                self.base.write('\t'*self.level)
                self.base.write(line)
                self.base.write('\n')
class Printer:
    def __init__(self, baseout):
        self.baseout = baseout
    def prints(self, *args):
        for x in args:
            self.baseout.write( str(x) + ' ')
        self.baseout.write('\n')
