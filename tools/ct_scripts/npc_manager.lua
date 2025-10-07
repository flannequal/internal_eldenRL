[ENABLE]
{$asm}
//aobScanModule(LockOnTarget_accessor_1,eldenring.exe,49 8B 06 49 8B CE FF 90 78 01 00 00 48 85 C0 74 20)
//alloc(LastLockOnTarget_1,4096)
//registersymbol(LastLockOnTarget_1)
//LastLockOnTarget_1:
//dq 0
//LockOnHook:
//mov [LastLockOnTarget_1],r14
//mov rax,[r14]
//mov rcx,r14
//mov r8,LockOnTarget_accessor_1+C
//push r8
//jmp qword ptr [rax+00000178]

//LockOnTarget_accessor_1:
//mov rax,LockOnHook
//jmp rax

{$lua}
local addr=AOBScanModuleUnique("eldenring.exe","0F 10 00 0F 11 44 24 70 0F 10 48 10 0F 11 4D 80 48 83 3D","+X")
local WorldChrMan
if addr then
   WorldChrMan=addr+24+readInteger(addr+19,true)
end

local function GetCharacterCount()
    local p=readQword(WorldChrMan)
    if not p then return 0 end
    local begin=readQword(p+0x1F1B8)
    local finish=readQword(p+0x1F1C0)
    if not begin or not finish or begin>=finish then return 0 end
    return (finish-begin)/8
end

local function TableFromMemRec(rec)
    local tbl={}
    local i
    for i=0,rec.DropDownCount-1 do
        tbl[tonumber(rec.DropDownValue[i])]=rec.DropDownDescription[i]
    end
    return tbl
end

local function GetPlayerPosAddr()
    local p=readQword(WorldChrMan)
    if not p then return end
    p=readQword(p+0x1E508)
    if not p then return end
    p=readQword(p+0x190)
    if not p then return end
    p=readQword(p+0x68)
    if not p then return end
    return p
end

local function GetPlayerPosition(asbytes)
    local p=GetPlayerPosAddr()
    if not p then return end
    if asbytes then return readBytes(p+0x70,12,true) end
    return readFloat(p+0x70),readFloat(p+0x74),readFloat(p+0x78)
end

local CharNames=TableFromMemRec(getAddressList().getMemoryRecordByID(22021343))
local TeamNames=TableFromMemRec(getAddressList().getMemoryRecordByID(5545))


WorldChrForm.OnClose=function(sender)
    getAddressList().getMemoryRecordByID(5539).Active=false
end
WorldChrForm.OnResize=function(sender)
    sender.CheckLockOn.Top=sender.ClientHeight-sender.CheckLockOn.Height-3
    sender.CheckPeek.Top=sender.ClientHeight-sender.CheckPeek.Height-3
    sender.CheckPeek.Left=sender.ClientWidth-sender.CheckPeek.Width
    sender.ButtonMoveToPlayer.Top=sender.ClientHeight-sender.ButtonMoveToPlayer.Height
    sender.ButtonMoveToPlayer.Left=sender.ClientWidth/3-sender.ButtonMoveToPlayer.Width/2-(sender.ClientWidth/3-(sender.ClientWidth-sender.ButtonKill.Width)/4)
    sender.ButtonKill.Top=sender.ClientHeight-sender.ButtonKill.Height
    sender.ButtonKill.Left=sender.ClientWidth/2-sender.ButtonKill.Width/2
    sender.ButtonMovePlayerTo.Top=sender.ClientHeight-sender.ButtonMovePlayerTo.Height
    sender.ButtonMovePlayerTo.Left=sender.ClientWidth*2/3-sender.ButtonMovePlayerTo.Width/2+(sender.ClientWidth/3-(sender.ClientWidth-sender.ButtonKill.Width)/4)
    sender.EditFind.Top=sender.ButtonKill.Top-sender.EditFind.Height-2
    sender.EditFind.Width=sender.ClientWidth
    sender.LV.setSize(sender.ClientWidth,sender.EditFind.Top-2)
end
WorldChrForm.EditFind.OnKeyDown=function(sender,key)
    if key==13 and sender.Text:len()>0 then
        local items=WorldChrForm.LV.Items
        local ff=-1
        local i
        local findstr=sender.Text:upper()
        local updated=false
        for i=0,items.Count-1 do
            local found=items[i].getCaption():upper():find(findstr)
            for j=0,items[i].SubItems.Count-1 do if not found then
                found=items[i].SubItems[j]:upper():find(findstr)
                j=items[i].SubItems.Count
            end end
            if found then
                if ff<0 then
                   ff=i
                end
                if not updated and items[i].Selected==false then
                   updated=true
                   WorldChrForm.LV.beginUpdate()
                end
                items[i].Selected=true
            else
                if not updated and items[i].Selected==true then
                   updated=true
                   WorldChrForm.LV.beginUpdate()
                end
                items[i].Selected=false
            end
        end
        if ff>=0 then
           sendMessage(WorldChrForm.LV.Handle,4115,ff,0)
        end
        if updated then
           WorldChrForm.LV.setFocus()
           WorldChrForm.LV.endUpdate()
        end
    end
end
WorldChrForm.LV.OnDblClick=function(sender)
    local item=sender.Selected
    if item then
       getAddressList().getMemoryRecordByID(5540).Address=item.getCaption()
       if ParamID then
       copyMemory(tonumber(item.getCaption(),16)+0x60,4,ParamID+4*6)
       end
    end
end

WorldChrForm.LV.OnKeyDown=function(sender,key)
    if key==67 and isKeyPressed(17) then
       CopyListView(sender)
    end
end

WorldChrForm.LV.OnData=function(sender,item)
    local p=readQword(WorldChrMan)
    if not p then return end
    local begin=readQword(p+0x1F1B8)
    if not begin then return end
    local px,py,pz
    px,py,pz=GetPlayerPosition()
    if not px or not py or not pz then return end
    local count=GetCharacterCount()
    if count and 0<=item.Index and item.Index<count then
       p=readQword(begin+item.Index*8)
       if not p or p<65536 then return end
       if WorldChrForm.CheckLockOn.Checked then
          local lp=readQword("LastLockOnTarget_1")
          if lp then item.Selected=lp==p end
       end
       item.setCaption(string.format("%X",p))
       local x=readInteger(p+8)
       if not x then return end
       item.SubItems.add(string.format("%X",x))
       x=readSmallInteger(p+0x74)
       if not x then return end
       item.SubItems.add(string.format("%X",x))
       x=readInteger(p+0x60,true)
       if not x then return end
       local s=CharNames[x]
       item.SubItems.add(s and tostring(x).. ':'..s or tostring(x))
       x=readByte(p+0x6C)
       if not x then return end
       local s=TeamNames[x]
       item.SubItems.add(s and tostring(x).. ':'..s or tostring(x))
       p=readQword(p+0x190)
       if not p then return end
       x=readQword(p)
       if not x then return end
       x=readQword(x+0x138)
       if not x then return end
       item.SubItems.add(string.format("%d/%d",x&0xFFFFFFFF,x>>32))

       x=readQword(p+0x18)
       if not x then return end
       x=readInteger(x+0x40,true)
       if not x then return end
       item.SubItems.add(tostring(x))

       p=readQword(p+0x68)
       if not p then return end
       x=readFloat(p+0x70)
       if not x then return end
       local y=readFloat(p+0x74)
       if not y then return end
       local z=readFloat(p+0x78)
       if not z then return end
       item.SubItems.add(string.format("% 8.3f,% 8.3f,% 8.3f",x,y,z))

       item.SubItems.add(string.format("%.3f",math.sqrt((px-x)*(px-x)+(py-y)*(py-y)+(pz-z)*(pz-z))))
    end
end

WorldChrForm.ButtonKill.OnClick=function(sender)
    local items=WorldChrForm.LV.Items
    for i=0,items.Count-1 do if items[i].Selected then
        local p=tonumber(items[i].getCaption(),16)
        if p then
           p=readQword(p+0x190)
           if p then
              p=readQword(p)
              if p then
                 writeInteger(p+0x138,0)
              end
           end
        end
    end end
    WorldChrForm.LV.setFocus()
end

WorldChrForm.ButtonMoveToPlayer.OnClick=function(sender)
    local items=WorldChrForm.LV.Items
    local plpos=GetPlayerPosition(true)
    if not plpos then return end
    for i=0,items.Count-1 do if items[i].Selected then
        local p=tonumber(items[i].getCaption(),16)
        if p then
           p=readQword(p+0x190)
           if p then
              p=readQword(p+0x68)
              if p then
                 writeBytes(p+0x70,plpos)
              end
           end
        end
    end end
    WorldChrForm.LV.setFocus()
end

WorldChrForm.ButtonMovePlayerTo.OnClick=function(sender)
    local plpos=GetPlayerPosAddr()
    if WorldChrForm.LV.Selected and plpos then
       local p=tonumber(WorldChrForm.LV.Selected.getCaption(),16)
        if p then
           p=readQword(p+0x190)
           if p then
              p=readQword(p+0x68)
              if p then
                 copyMemory(p+0x70,12,plpos+0x70)
              end
           end
        end
    end
    WorldChrForm.LV.setFocus()
end

WorldChrForm.CheckLockOn.OnChange=function(sender)
    pcall(WorldChrForm.LV.setFocus)
end

WorldChrForm.CheckPeek.OnChange=function(sender)
    pcall(WorldChrForm.LV.setFocus)
    local PeekTarget=getAddressSafe("CamFollowAlt")
    if sender.Checked then
      if not PeekTarget then
         getAddressList().getMemoryRecordByID(22021410).Active=true
      end
      PeekTarget=getAddressSafe("CamFollowAlt")
      if PeekTarget then
         local p=tonumber(WorldChrForm.LV.Selected.getCaption(),16)
         if p then writeQword(PeekTarget,p)end
      end
    elseif PeekTarget then
      writeQword(PeekTarget,0)
    end
end

WorldChrTimer=createTimer(nil,true)
WorldChrTimer.Interval=256
WorldChrTimer.OnTimer=function(timer)
    WorldChrForm.LV.Items.Count=GetCharacterCount()
    if WorldChrForm.CheckLockOn.Checked then
       if WorldChrForm.LV.ItemIndex<0 then

       end
       if WorldChrForm.LV.ItemIndex>=0 then
           sendMessage(WorldChrForm.LV.Handle,4115,WorldChrForm.LV.ItemIndex,0)
       end
    end
    WorldChrForm.LV.repaint()
end

WorldChrForm.OnResize(WorldChrForm)
WorldChrTimer.OnTimer(timer)
WorldChrForm.show()
[DISABLE]
{$asm}
//LockOnTarget_accessor_1:
//db 49 8B 06 49 8B CE FF 90 78 01 00 00 48 85 C0 74 20
//dealloc(LastLockOnTarget_1)
//unregistersymbol(LastLockOnTarget_1)
{$lua}
if WorldChrTimer then
   WorldChrTimer.destroy()
   WorldChrTimer=nil
end
WorldChrForm.CheckLockOn.Checked=false
WorldChrForm.CheckPeek.Checked=false
WorldChrForm.hide()
WorldChrForm.LV.Items.Count=0
WorldChrForm.EditFind.Text=""