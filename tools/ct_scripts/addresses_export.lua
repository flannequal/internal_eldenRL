-- export_bases_json.lua

-- A helper function to write a Lua table to a file in JSON format.
local json = {}
json.write = function(t, fh, indent)
  indent = indent or ""
  if type(t) == "table" then
    fh:write("{\n")
    local first = true
    for k, v in pairs(t) do
      if not first then fh:write(",\n") else first = false end
      fh:write(string.format('%s  "%s": ', indent, tostring(k)))
      json.write(v, fh, indent .. "  ")
    end
    fh:write("\n" .. indent .. "}")
  elseif type(t) == "string" then
    fh:write(string.format('"%s"', t))
  elseif type(t) == "number" then
    fh:write(tostring(t))
  elseif type(t) == "boolean" then
    fh:write(tostring(t))
  else
    fh:write('"<' .. type(t) .. '>"')
  end
end

-- This function now only gets the base addresses and exports them.
function export_bases(outfile, baseNames)
  if not getAddressSafe(process) then
    print("No process attached")
    return false
  end
  local fh = io.open(outfile, "w")
  if not fh then
    print("Cannot open " .. outfile)
    return false
  end

  -- Create a table of the base addresses.
  local bases = {}
  local moduleBase = getAddress(process)
  for i, name in ipairs(baseNames) do
    local addr = getAddressSafe(name)
    if addr then
      bases[name] = string.format("0x%X", addr - moduleBase)
    end
  end

  -- Prepare the final output table, containing only the bases.
  local out = { bases = bases }

  -- Write the table to the file and close it.
  json.write(out, fh)
  fh:close()
  print("Exported bases to " .. outfile)
  return true
end

-- Usage: Call the function with your desired output path and list of names.

export_bases("C:\\elden_bases_export.json", {
  "GameDataMan", "WorldChrMan", "MapItemMan", "GameMan", "FieldArea",
  "DamageCtrl", "MsgRepository", "NetManImp", "CSRegulationManagerImp",
  "PARAM", "EventFlagMan", "CSFlipper", "CSLuaEventManager", "hudngaddr",
  "MapLight", "CHR_DBG_FLAGS", "CHR_DBG", "EmkSystem", "MsbPointMan",
  "WorldMapMan"})