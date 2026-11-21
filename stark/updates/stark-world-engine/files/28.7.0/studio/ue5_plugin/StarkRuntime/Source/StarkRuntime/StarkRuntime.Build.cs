// Stark World Engine Runtime module rules.
// Module rules: https://dev.epicgames.com/documentation/en-us/unreal-engine/module-properties-in-unreal-engine
using UnrealBuildTool;

public class StarkRuntime : ModuleRules
{
	public StarkRuntime(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core", "CoreUObject", "Engine", "InputCore", "AIModule", "GameplayTasks", "NavigationSystem",
			"Json", "JsonUtilities", "Landscape"
		});

		if (Target.bBuildEditor)
		{
			// editor-only helpers (landscape creation, start Play-In-Editor for the smoke test)
			PrivateDependencyModuleNames.Add("UnrealEd");
		}
	}
}
