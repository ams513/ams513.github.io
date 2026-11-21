@tool
extends MeshInstance3D
## Stark World Engine Runtime water plane: gentle animated normals, fresnel tint from the level's mood (no textures needed).

@export var water_color: Color = Color(0.05, 0.3, 0.4, 0.82)
@export var size: float = 160.0

const SHADER_CODE := """
shader_type spatial;
render_mode cull_disabled, depth_draw_always;
uniform vec4 tint : source_color = vec4(0.05, 0.3, 0.4, 0.82);
uniform sampler2D wave_a : hint_normal, filter_linear_mipmap, repeat_enable;
uniform sampler2D wave_b : hint_normal, filter_linear_mipmap, repeat_enable;
varying vec3 wpos;
void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	VERTEX.y += sin(wpos.x * 0.35 + TIME * 1.2) * 0.04 + cos(wpos.z * 0.3 + TIME) * 0.04;
}
void fragment() {
	vec2 uv = wpos.xz * 0.06;
	vec3 na = texture(wave_a, uv + vec2(TIME * 0.02, TIME * 0.013)).rgb;
	vec3 nb = texture(wave_b, uv * 1.7 - vec2(TIME * 0.017, -TIME * 0.021)).rgb;
	NORMAL_MAP = mix(na, nb, 0.5);
	float fres = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 3.0);
	ALBEDO = mix(tint.rgb, vec3(0.75, 0.85, 0.95), fres * 0.35);
	ALPHA = clamp(tint.a + fres * 0.2, 0.0, 1.0);
	METALLIC = 0.1;
	ROUGHNESS = 0.04;
	SPECULAR = 0.6;
}
"""


func _ready() -> void:
	var pm := PlaneMesh.new()
	pm.size = Vector2(size, size)
	pm.subdivide_width = 48
	pm.subdivide_depth = 48
	mesh = pm
	var sh := Shader.new()
	sh.code = SHADER_CODE
	var m := ShaderMaterial.new()
	m.shader = sh
	m.set_shader_parameter("tint", water_color)
	for k in ["wave_a", "wave_b"]:
		var n := FastNoiseLite.new()
		n.frequency = 0.02 if k == "wave_a" else 0.035
		n.seed = 7 if k == "wave_a" else 19
		var tex := NoiseTexture2D.new()
		tex.noise = n
		tex.seamless = true
		tex.as_normal_map = true
		tex.bump_strength = 4.0
		tex.width = 256
		tex.height = 256
		m.set_shader_parameter(k, tex)
	material_override = m
	cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
