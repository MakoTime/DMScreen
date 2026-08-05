_VIEW_MODULES = {
	"DMScreen": ("ui.views.dm_screen", "DMScreen"),
	"FrameEditorDialog": ("ui.views.menu", "FrameEditorDialog"),
	"LayerEditView": ("ui.views.layer_edit", "LayerEditView"),
	"LayerPanel": ("ui.views.layers", "LayerPanel"),
	"LayerTable": ("ui.views.layers", "LayerTable"),
	"MenuBar": ("ui.views.menu", "MenuBar"),
	"MouseActionMenu": ("ui.views.mouse_action", "MouseActionMenu"),
	"MouseActionState": ("ui.views.mouse_action", "MouseActionState"),
	"PlayerControlsPanel": ("ui.views.player_controls", "PlayerControlsPanel"),
	"PlayerHandler": ("ui.views.player_handler", "PlayerHandler"),
	"PlayerScreen": ("ui.views.player_screen", "PlayerScreen"),
	"ScenePreview": ("ui.views.layer_edit", "ScenePreview"),
	"SidePanel": ("ui.views.side_panel", "SidePanel"),
	"ZoomHandler": ("ui.views.zoom_handler", "ZoomHandler"),
}

__all__ = list(_VIEW_MODULES)


def __getattr__(name):
	if name not in _VIEW_MODULES:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
	module_name, attribute_name = _VIEW_MODULES[name]
	module = __import__(module_name, fromlist=[attribute_name])
	value = getattr(module, attribute_name)
	globals()[name] = value
	return value
