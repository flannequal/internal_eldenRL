[ENABLE]
{$lua}
local addr=AOBScanModuleUnique("eldenring.exe","48 89 44 24 50 48 8B D9 C7 44 24 24 00 00 00 00 48 8B 0D","+X")
if addr then
   registerSymbol("CameraBase",addr+23+readInteger(addr+19,true),true)
end
{$asm}
aobScanModule(LockOnTarget_accessor,eldenring.exe,48 8B 48 08 49 89 8D B0 06 00 00 49 8B CE E8)
alloc(LastLockOnTarget,4096,LockOnTarget_accessor)
registersymbol(LastLockOnTarget)
LastLockOnTarget:
dq 0
LockOnHook:
mov [LastLockOnTarget],rax
mov rcx,[rax+08]
mov [r13+000006B0],rcx
jmp LockOnTarget_accessor+B

LockOnTarget_accessor:
jmp LockOnHook

[DISABLE]
LockOnTarget_accessor:
db 48 8B 48 08 49 89 8D B0 06 00 00 49 8B CE E8
dealloc(LastLockOnTarget)
unregistersymbol(LastLockOnTarget)