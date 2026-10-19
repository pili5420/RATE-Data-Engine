"""CB01 is offline corrective engineering only. No Native execution authority."""
def main():
 raise RuntimeError('CB01_OFFLINE_ONLY_NO_NATIVE_EXECUTION_AUTHORIZATION')
if __name__=='__main__':
 print('CB01_OFFLINE_ONLY_NATIVE_EXECUTION_NOT_AUTHORIZED')
 raise SystemExit(1)
