Scriptname SLOVE_Utils Hidden
{Stateless helpers shared across the SLO VE scripts - each used to exist as
 per-script copies (seven of the logging shim, five each of the plugin probe
 and the pause check). Global functions cannot hold state, so anything needing
 a per-instance cache or a config knob (printdebug, the hot API probes) stays
 in its script.}

;True when the plugin is in the load order. PO3's IsPluginFound (the
;implementation the Directors always used) rather than Game.GetModByName,
;which silently fails for ESL-flagged plugins - the Voice/Resistance copies
;carried that trap.
Bool Function isDependencyReady(String modname) Global
	return PO3_SKSEFunctions.IsPluginFound(modname)
EndFunction

;Error-level line into the SLOVE user log (SLOVE.0.log)
Function WritetoErrorlogs(string Header = "Not Specified", String contents = "") Global
	SLOVE_Log.WriteLog(Header + " : " + contents, 2)
EndFunction

;A pack's variation is a consumer label: "D" (tag-shaped) packs dispatch like
;"B" - AudioUtil's tag scoring keys on facts, not on the label
String Function DispatchVariation(String a_variation) Global
	if a_variation == "D"
		return "B"
	endif
	return a_variation
EndFunction

;True while a menu has the scene frozen. SKSE Menu Framework and other ImGui
;overlays freeze the game WITHOUT entering menu mode, so the Papyrus VM keeps
;ticking and Utility.IsInMenuMode() sees a running game; AudioUtil reads the
;engine's freeze flag natively (API v7). Older AudioUtil: always false = the
;previous behavior. Stateless (one extra GetAPIVersion native per call versus
;the old per-instance caches - noise at tick cadence, and a probe can never go
;stale across an AudioUtil upgrade again).
Bool Function GamePaused() Global
	return AudioUtil.GetAPIVersion() >= 7 && AudioUtil.IsGamePaused()
EndFunction
