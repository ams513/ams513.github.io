// Stark World Engine Runtime terrain: four layers (grass, rock, sand, snow) blended by slope, height and water level.
// Drop albedo textures into the Terrain node's layer slots (Poly Haven / ambientCG / Megascans), or paint your own
// RGBA splat map (R grass, G rock, B sand, A snow) and enable it with the splat_map slot.
shader_type spatial;
render_mode cull_back, diffuse_burley, specular_schlick_ggx;

uniform vec3 grass_color : source_color = vec3(0.3, 0.5, 0.25);
uniform vec3 rock_color : source_color = vec3(0.45, 0.43, 0.42);
uniform vec3 sand_color : source_color = vec3(0.78, 0.7, 0.5);
uniform vec3 snow_color : source_color = vec3(0.92, 0.94, 0.97);
uniform sampler2D grass_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D rock_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D sand_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform sampler2D snow_tex : source_color, filter_linear_mipmap, repeat_enable;
uniform bool use_grass_tex = false;
uniform bool use_rock_tex = false;
uniform bool use_sand_tex = false;
uniform bool use_snow_tex = false;
uniform sampler2D splat_tex : filter_linear;
uniform bool use_splat = false;
uniform sampler2D variation_tex : filter_linear_mipmap, repeat_enable;
uniform float water_level = -1000.0;
uniform float snow_line = 1000.0;
uniform float uv_scale = 0.25;
uniform float edge_fade = 0.0;

varying vec3 wpos;
varying vec3 wnrm;

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	wnrm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

void fragment() {
	float slope = 1.0 - clamp(wnrm.y, 0.0, 1.0);
	// same blend as the Stark World Engine browser engine: rock by slope, a thin shore band just above the water line
	float w_rock = clamp(slope * 3.5 - 0.35, 0.0, 1.0);
	float w_sand = clamp((water_level + 0.35 - wpos.y) * 2.5, 0.0, 1.0) * (1.0 - w_rock);
	float w_snow = smoothstep(snow_line - 0.5, snow_line + 1.5, wpos.y) * (1.0 - w_rock * 0.6);
	float w_grass = max(0.0, 1.0 - w_rock - w_sand - w_snow);
	vec4 w = vec4(w_grass, w_rock, w_sand, w_snow);
	if (use_splat) {
		w = texture(splat_tex, UV2);
	}
	w /= max(0.0001, w.x + w.y + w.z + w.w);
	vec2 uv = wpos.xz * uv_scale;
	float v = texture(variation_tex, wpos.xz * 0.015).r;
	float k = 0.82 + 0.36 * v;
	vec3 g = use_grass_tex ? texture(grass_tex, uv).rgb : grass_color * k;
	vec3 r = use_rock_tex ? texture(rock_tex, uv * 0.7).rgb : rock_color * (0.9 + 0.2 * v);
	vec3 s = use_sand_tex ? texture(sand_tex, uv).rgb : sand_color * (0.92 + 0.16 * v);
	vec3 n = use_snow_tex ? texture(snow_tex, uv).rgb : snow_color;
	vec3 col = g * w.x + r * w.y + s * w.z + n * w.w;
	ALBEDO = col * (1.0 - edge_fade);
	ROUGHNESS = mix(0.95, 0.55, w.w);
}
