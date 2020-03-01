#!/usr/bin/python
'''
Convert DWARF annotations in ELF executable to C declarations
'''
# Copyright (C) 2012 W.J. van der Laan
#
# Permission is hereby granted, free of charge, to any person obtaining a copy 
# of this software and associated documentation files (the "Software"), to deal 
# in the Software without restriction, including without limitation the rights 
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies 
# of the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all 
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT 
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION 
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE 
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
from __future__ import print_function, division, unicode_literals
import argparse

import sys, os
from collections import defaultdict

DEBUG=False

# Logging
def error(x):
    print('Error: '+x, file=sys.stderr)
def warning(x):
    print('Warning: '+x, file=sys.stderr)
def progress(x):
    print('* '+x, file=sys.stderr)

# Command-line argument parsing
def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', action='store', type=str, required=True, dest='binfile', default=None)
    parser.add_argument('-f', action='store', type=str, dest='srcfile', default=None)
    parser.add_argument('-t', action='store', type=str, dest='type', choices=('struct', 'union'), default=None)
    parser.add_argument('root', action='store', type=str, default=None)
    return parser.parse_args()

from bintools.dwarf import DWARF
from bintools.dwarf.enums import DW_AT, DW_TAG, DW_LANG, DW_ATE, DW_FORM, DW_OP
from pycunparser.c_generator import CGenerator
from pycunparser import c_ast
from dwarfhelpers import get_flag, get_str, get_int, get_ref, not_none, expect_str
import struct

def resolve_typedef(dwarf, cu, t):
	type_ = get_ref(t, 'type')
	if type_ is not None:
		type_die = cu.dies_dict[type_]
		return type_die

	return None

def find_root_in_cu(dwarf, cu, type, root):
	cu_die = cu.compile_unit

	for child in cu_die.children:
		name = get_str(child, 'name')
		if name is not None and name == root:
			if type is None and child.tag in [DW_TAG.typedef]:
				type_die = resolve_typedef(dwarf, cu, child)
				if type_die is not None and type_die.tag in [DW_TAG.structure_type, DW_TAG.union_type]:
					return type_die
			elif type in ['struct'] and child.tag in [DW_TAG.structure_type]:
				return child
			elif type in ['union'] and child.tag in [DW_TAG.union_type]:
				return child

	return None

def get_member(dwarf, cu, c, parent):
	offset = None
	name = get_str(c, 'name')
	type = get_ref(c, 'type')
	array = False
	array_dims = None
	size = None
	cu_offset = None

	if parent.tag in [DW_TAG.structure_type]:
		if 'data_member_location' in c.attr_dict:
			ml = c.attr_dict['data_member_location']
			if ml.form in ['block', 'block1']:
				expr = ml.value
				if len(expr.instructions) >= 1 and expr.instructions[0].opcode == DW_OP.plus_uconst:
					offset = expr.instructions[0].operand_1
        # we know that DW_TAG.union_type has all members at offset = 0
	elif parent.tag in [DW_TAG.union_type]:
		offset = 0

	if type is not None and type in cu.dies_dict.keys() and cu.dies_dict[type] is not None:
		type = cu.dies_dict[type]

                # base_type member is pass-through
                # we deal with pointers, struct and union members separately 
		if type.tag in [DW_TAG.base_type, DW_TAG.structure_type, DW_TAG.union_type, DW_TAG.pointer_type]:
			pass

                # we find the base_type of enum members and use it as type
		elif type.tag in [DW_TAG.enumeration_type]:
			reftype = get_ref(type, 'type')
			if reftype is not None and reftype in cu.dies_dict.keys():
				type = cu.dies_dict[reftype]
			else:
				type = None

                # we recursively deal with typdef until it resolves to base_type
                # if it resolves to enum, we replace with the base_type of the enum
                # if it resolves to struct or union, we let it pass, we deal with it later
		elif type.tag in [DW_TAG.typedef]:
			while type.tag in [DW_TAG.typedef]:
				type = resolve_typedef(dwarf, cu, type)
				if type is None:
					break
			if type is not None:
				if type.tag in [DW_TAG.enumeration_type]:
					reftype = get_ref(type, 'type')
					if reftype is not None and reftype in cu.dies_dict.keys():
						type = cu.dies_dict[reftype]
					else:
						type = None
				elif type.tag not in [DW_TAG.pointer_type, DW_TAG.base_type, DW_TAG.structure_type, DW_TAG.union_type]:
					error('member %s typedef resolved to unsupported type %s' % (name, DW_TAG.fmt(type.tag)))
					type = None

		# We keep information of array dimensions and keep type as the element type
		elif type.tag in [DW_TAG.array_type]:
			array = True
			array_dims = []
			for val in type.children:
				if val.tag == DW_TAG.subrange_type:
					array_dims.append(get_int(val, 'upper_bound') + 1)

			subtype = get_ref(type, 'type')
			if subtype is not None and subtype in cu.dies_dict.keys() and cu.dies_dict[subtype] is not None:
				type = cu.dies_dict[subtype]
				if type.tag in [DW_TAG.typedef]:
					while type.tag in [DW_TAG.typedef]:
						type = resolve_typedef(dwarf, cu, type)
						if type is None:
							break
					if type is not None:
						if type.tag in [DW_TAG.enumeration_type]:
							reftype = get_ref(type, 'type')
							if reftype is not None and reftype in cu.dies_dict.keys():
								type = cu.dies_dict[reftype]
							else:
								type = None
						elif type.tag not in [DW_TAG.pointer_type, DW_TAG.base_type, DW_TAG.structure_type, DW_TAG.union_type]:
							error('member %s typedef resolved to unsupported type %s' % (name, DW_TAG.fmt(type.tag)))
							type = None

		else:
			error('unsupported type %s for member %s' % (DW_TAG.fmt(type.tag), name))
			type = None

	# get size of type and cu_offset of type for array manipulation and future references
	if type is not None:
		size = get_int(type, 'byte_size')
		cu_offset = type.offset

		typename = get_str(type, 'name')
		if typename is None:
			typename = 'anonymous' 

		if type.tag in [DW_TAG.structure_type, DW_TAG.union_type]:
			if type.tag in [DW_TAG.structure_type]:
				typename = 'struct ' + typename
			else:
				typename = 'union ' + typename
		if type.tag in [DW_TAG.pointer_type]:
			typename = 'pointer'
	

	return name, {'offset':offset, 'size':size, 'typename':typename, 'type':type, 'array':array, 'array_dims':array_dims, 'cu_offset':cu_offset}

def print_type(dwarf, cu, root, indent, rby):
	for c in root.children:
		if c.tag in [DW_TAG.member]:
			name, attribs = get_member(dwarf, cu, c, root)
			if name is None:
				error("could not get valid member")
				exit(1)
			if attribs['typename'] is None or attribs['type'] is None :
				error("None type for member %s" % name)
				exit(1)
			if attribs['offset'] is None:
				error("None offset for member %s" % name)
				exit(1)
			if attribs['type'] is not None:
				if attribs['size'] is None:
					error("None sizefor member %s" % name)
					exit(1)
				if attribs['cu_offset'] is None:
					error("None cu_offset for member %s" % name)
					exit(1)
				if not attribs['cu_offset'] in cu.dies_dict.keys():
					error("type with cu_offset not found in cu.dies_dict for member %s" % name)
					exit(1)
			if attribs['array'] and attribs['array_dims'] is None:
				error("None array_dims for array member %s" % name)
				exit(1)

			
			if len(name) > 128 or len(attribs['typename']) > 128:
				error("Name or type len exceeds 128 for member %s" % name)
				exit(1)

			if attribs['array'] and len(attribs['array_dims']) > 4:
				error("array dims len exceeds 4 for member %s" % name)
				exit(1)

			by = struct.pack('B', indent)
			by += struct.pack('>i', attribs['offset'])
			by += struct.pack('>i', (attribs['size'] or 0))
			by += struct.pack('B', (1 if attribs['array'] else 0))

			dims = list(attribs['array_dims'] or [1])
			dims.extend([-1] * (4 - len(dims)))
			for i in range(len(dims)):
				by += struct.pack('>i', dims[i])

			name_by = bytearray(name, 'utf-8')
			name_by += bytearray(128 - len(name_by))
			by += name_by

			type_by = bytearray('' if attribs['typename'].startswith('struct') or attribs['typename'].startswith('union') else attribs['typename'], 'utf-8')
			type_by += bytearray(128 - len(type_by))
			by += type_by

			rby += by
			'''
			error('%s,%s,%s,%s,%s,%s,%s' % (
				indent,
				name,
				attribs['offset'],
				attribs['size'] or 0,
				1 if attribs['array'] else 0,
				':'.join([(lambda x : str(x))(x) for x in attribs['array_dims']]) if attribs['array'] else '1',
				'indirect' if attribs['typename'].startswith('struct') or attribs['typename'].startswith('union') else attribs['typename']))
			'''
			if attribs['typename'].startswith('struct') or attribs['typename'].startswith('union'):
				rby = print_type(dwarf, cu, cu.dies_dict[attribs['cu_offset']], indent + 1, rby)

	return rby

def main():
	args = parse_arguments()
	if not os.path.isfile(args.binfile):
		error("No such file %s" % args.infile)
		exit(1)

	dwarf = DWARF(args.binfile)

	root = None
	for i, c in enumerate(dwarf.info.cus):
		cu = None
		if args.srcfile is None:
			cu = c
		elif args.srcfile is not None and c.name == args.srcfile:
			cu = c
		
		if cu:
			root = find_root_in_cu(dwarf, cu, args.type, args.root)
			if root:
				break

	if cu is None:
		error("No such cu %s" % args.srcfile)
		exit(1)

	if root is None:
		error("No such root %s%s" % (args.type + ' ' if args.type is not None else '', args.root))
		exit(1)

	rby = print_type(dwarf, cu, root, 0, bytearray('', 'utf-8'))

	sys.stdout.write(rby)

if __name__ == '__main__':
    main()
