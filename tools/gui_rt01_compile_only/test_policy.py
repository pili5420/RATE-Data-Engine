"""Parser/command negative tests. Synthetic bytes are NOT compile evidence."""
import struct
import unittest
import validate_evidence as v


def object_fixture(machine=0x8664, flags=0, data=b'', name=b'.drectve', symbols=b'', symcount=0, strings=b'\x04\x00\x00\x00'):
    section = name.ljust(8, b'\0') + struct.pack('<IIIIIIHHI', 0, 0, len(data), 60 if data else 0, 0, 0, 0, 0, flags)
    pointer = 60 + len(data) if symcount else 0
    return struct.pack('<HHIIIHH', machine, 1, 0, pointer, symcount, 0, 0) + section + data + symbols + (strings if symcount else b'')


class ObjectBoundaryTests(unittest.TestCase):
    def test_empty_declaration_x64_shape(self): v.coff(object_fixture(), 'x64')
    def test_empty_declaration_x86_shape(self): v.coff(object_fixture(machine=0x14c), 'x86')
    def test_target_architecture_mismatch(self):
        with self.assertRaises(v.Rejected): v.coff(object_fixture(), 'x86')
    def test_unknown_architecture(self):
        with self.assertRaises(v.Rejected): v.coff(object_fixture(), 'arm64')
    def test_pe_image_rejected(self):
        with self.assertRaises(v.Rejected): v.coff(b'MZ' + bytes(100), 'x64')
    def test_optional_header_rejected(self):
        b=bytearray(object_fixture()); struct.pack_into('<H',b,16,1)
        with self.assertRaises(v.Rejected): v.coff(bytes(b),'x64')
    def test_executable_characteristic_rejected(self):
        b=bytearray(object_fixture()); struct.pack_into('<H',b,18,2)
        with self.assertRaises(v.Rejected): v.coff(bytes(b),'x64')
    def test_code_section_rejected(self):
        with self.assertRaises(v.Rejected): v.coff(object_fixture(flags=0x20,data=b'\xc3'), 'x64')
    def test_execute_section_rejected(self):
        with self.assertRaises(v.Rejected): v.coff(object_fixture(flags=0x20000000,data=b'\xc3'), 'x64')
    def test_text_content_rejected(self):
        with self.assertRaises(v.Rejected): v.coff(object_fixture(name=b'.text',data=b'\xc3'), 'x64')
    def test_truncated_header_rejected(self):
        with self.assertRaises(v.Rejected): v.coff(bytes(19),'x64')
    def test_truncated_section_rejected(self):
        with self.assertRaises(v.Rejected): v.coff(object_fixture()[:-1],'x64')
    def test_section_pointer_rejected(self):
        b=bytearray(object_fixture(data=b'x'));struct.pack_into('<I',b,40,999999)
        with self.assertRaises(v.Rejected): v.coff(bytes(b),'x64')
    def test_unresolved_external_rejected(self):
        symbol=struct.pack('<8sIhHBB',b'__imp_X',0,0,0,2,0)
        with self.assertRaises(v.Rejected): v.coff(object_fixture(symbols=symbol,symcount=1),'x64')
    def test_defined_function_rejected(self):
        symbol=struct.pack('<8sIhHBB',b'callback',0,1,0x20,2,0)
        with self.assertRaises(v.Rejected): v.coff(object_fixture(symbols=symbol,symcount=1),'x64')
    def test_main_symbol_rejected(self):
        symbol=struct.pack('<8sIhHBB',b'main',0,1,0,2,0)
        with self.assertRaises(v.Rejected): v.coff(object_fixture(symbols=symbol,symcount=1),'x64')
    def test_auxiliary_overflow_rejected(self):
        symbol=struct.pack('<8sIhHBB',b'@comp.id',0,-1,0,3,1)
        with self.assertRaises(v.Rejected): v.coff(object_fixture(symbols=symbol,symcount=1),'x64')
    def test_absolute_compiler_marker_allowed(self):
        symbol=struct.pack('<8sIhHBB',b'@comp.id',0,-1,0,3,0)
        v.coff(object_fixture(symbols=symbol,symcount=1),'x64')


class CommandBoundaryTests(unittest.TestCase):
    source='D:\\repo\\tools\\gui_runtime_readiness\\windows_abi_compile_only.cpp'
    obj='D:\\temp\\windows_abi_compile_only.obj'
    def args(self): return v.FLAGS + ['/Fo'+self.obj,self.source]
    def test_fixed_command_accepted(self): v.validate_command(self.args(),self.source,self.obj)
    def test_link_flag_rejected(self):
        with self.assertRaises(v.Rejected): v.validate_command(self.args()+['/link'],self.source,self.obj)
    def test_response_file_rejected(self):
        with self.assertRaises(v.Rejected): v.validate_command(self.args()+['@override.rsp'],self.source,self.obj)
    def test_removed_compile_only_rejected(self):
        with self.assertRaises(v.Rejected): v.validate_command([x for x in self.args() if x!='/c'],self.source,self.obj)
    def test_warning_suppression_rejected(self):
        with self.assertRaises(v.Rejected): v.validate_command(self.args()+['/wd4996'],self.source,self.obj)
    def test_missing_warnings_as_errors_rejected(self):
        with self.assertRaises(v.Rejected): v.validate_command([x for x in self.args() if x!='/WX'],self.source,self.obj)
    def test_executable_output_rejected(self):
        with self.assertRaises(v.Rejected): v.validate_command(v.FLAGS+['/FoD:\\x.exe',self.source],self.source,'D:\\x.exe')
    def test_unapproved_source_rejected(self):
        with self.assertRaises(v.Rejected): v.validate_command(v.FLAGS+['/Fo'+self.obj,'evil.cpp'],'evil.cpp',self.obj)


if __name__ == '__main__': unittest.main(verbosity=2)
