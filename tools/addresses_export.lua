-- export_full_table_json.lua
local json = {
  write = function(t, fh, indent)
    indent = indent or ""
    if type(t) == "table" then
      fh:write("{\n")
      local first = true
      for k,v in pairs(t) do
        if not first then fh:write(",\n") else first=false end
        fh:write(string.format('%s  "%s": ', indent, tostring(k)))
        json.write(v, fh, indent.."  ")
      end
      fh:write("\n"..indent.."}")
    elseif type(t) == "string" then
      fh:write(string.format('"%s"', t))
    elseif type(t) == "number" then
      fh:write(tostring(t))
    elseif type(t) == "boolean" then
      fh:write(tostring(t))
    else
      fh:write('"<'..type(t)..'>"')
    end
  end
}

function export_full_table(outfile, baseNames)
  if not getAddressSafe(process) then print("No process attached") return false end
  local fh = io.open(outfile, "w")
  if not fh then print("Cannot open "..outfile) return false end

  -- bases
  local bases = {}
  local moduleBase = getAddress(process)
  for i,name in ipairs(baseNames) do
    local addr = getAddressProcessSafe(name) or getAddressSafe(name)
    if addr then bases[name] = string.format("0x%X", addr - moduleBase) end
  end

  -- address list (memory records)
  local records = {}
  local al = getAddressList()
  for i=0, al.Count-1 do
    local mr = al.getMemoryRecord(i)
    local desc = mr.Description or ("addr_"..i)
    local rec = {}
    -- address string (resolved absolute address if symbol exists)
    local addrStr = mr.Address
    rec["address"] = tostring(addrStr)
    -- pointer info: CE memory record exposes pointer and offsets in the UI; we'll capture the offsets string
    if mr.IsPointer then
      local ptrOffsets = {}
      for j = 0, mr.PointerCount-1 do
        table.insert(ptrOffsets, string.format("0x%X", mr.getPointer(j)))
      end
      rec["pointer_offsets"] = ptrOffsets
    end
    rec["var_type"] = mr.VarType or mr.Type or "unknown"
    records[desc] = rec
  end

  local out = { bases = bases, records = records }
  json.write(out, fh)
  fh:close()
  print("Exported full table to "..outfile)
  return true
end

-- Usage (change path & baseNames as needed)
export_full_table("C:\\elden_full_export.json",
  {"GameDataMan","WorldChrMan","MapItemMan","GameMan","FieldArea","DamageCtrl","MsgRepository"})
