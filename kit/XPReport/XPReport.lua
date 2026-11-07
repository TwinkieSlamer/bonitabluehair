-- XPReport: remembers your level and XP so the XP uploader can post it to bonitabluehair.com.
-- It tracks XP only: level, XP into the level, XP the level needs, and the time of each level-up.
-- WoW writes this to disk (SavedVariables\XPReport.lua) when you log out or type /reload.

XPReportDB = XPReportDB or {}

local function now()
  if GetServerTime then return GetServerTime() end
  return time()
end

local function entryFor(name)
  local entry = XPReportDB[name]
  if type(entry) ~= "table" then
    entry = {}
    XPReportDB[name] = entry
  end
  return entry
end

local function record(dingLevel)
  local name = UnitName("player")
  if not name or name == "" or name == UNKNOWNOBJECT then return end
  local entry = entryFor(name)
  local level = UnitLevel("player") or 0
  if dingLevel then
    if dingLevel > level then level = dingLevel end
    entry.dings = entry.dings or {}
    local lastDing = entry.dings[#entry.dings]
    if not lastDing or lastDing.level ~= dingLevel then
      table.insert(entry.dings, { level = dingLevel, time = now() })
    end
  end
  entry.level = level
  entry.xp = UnitXP("player") or 0
  entry.xpMax = UnitXPMax("player") or 0
  entry.time = now()
end

local frame = CreateFrame("Frame")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("PLAYER_XP_UPDATE")
frame:RegisterEvent("PLAYER_LEVEL_UP")
frame:RegisterEvent("PLAYER_LOGOUT")
frame:SetScript("OnEvent", function(_, event, arg1)
  if event == "PLAYER_LEVEL_UP" then
    record(tonumber(arg1))
  else
    record()
  end
  if event == "PLAYER_ENTERING_WORLD" and arg1 then
    print("|cff5ad6c6XPReport|r is recording your XP. Type /xpreport to check it.")
  end
end)

SLASH_XPREPORT1 = "/xpreport"
SlashCmdList.XPREPORT = function()
  record()
  local entry = XPReportDB[UnitName("player")]
  if not entry then return end
  local pct = (entry.xpMax or 0) > 0 and math.floor(entry.xp / entry.xpMax * 100) or 0
  print(string.format("|cff5ad6c6XPReport|r level %d, %d / %d XP (%d%%). Saved when you log out or /reload.",
    entry.level or 0, entry.xp or 0, entry.xpMax or 0, pct))
end
