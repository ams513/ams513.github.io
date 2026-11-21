// Stark World Engine Runtime - editor helpers the build scripts call from Python (unreal.StarkEditorLibrary):
// a real Landscape from the world's heights, and starting / stopping Play-In-Editor for the smoke test.
// Editor-only bodies (WITH_EDITOR); in a packaged game they do nothing.
// UBlueprintFunctionLibrary: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Kismet/UBlueprintFunctionLibrary
// ALandscapeProxy::Import: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Landscape/ALandscapeProxy/Import
// UEditorEngine::RequestPlaySession: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Editor/UnrealEd/UEditorEngine/RequestPlaySession
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "StarkEditorLibrary.generated.h"

class ALandscape;
class UMaterialInterface;

UCLASS()
class STARKRUNTIME_API UStarkEditorLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()
public:
	/** Creates a Landscape in the editor world from 16-bit heights (32768 = 0; one unit = Scale.Z / 128 cm).
	 *  SizeX - 1 and SizeY - 1 must be multiples of QuadsPerSection * SectionsPerComponent (e.g. 253 or 505 with 63/1). */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine|Editor")
	static ALandscape* CreateLandscapeFromHeights(const TArray<int32>& Heights, int32 SizeX, int32 SizeY, FVector Location,
		FVector Scale, UMaterialInterface* Material, int32 QuadsPerSection = 63, int32 SectionsPerComponent = 1);

	/** Starts Play-In-Editor (used by stark_pie_smoke.py; UE 5.4 Python has no direct call for it). */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine|Editor")
	static bool StartPlayInEditor();

	UFUNCTION(BlueprintCallable, Category = "Stark World Engine|Editor")
	static bool StopPlayInEditor();

	UFUNCTION(BlueprintPure, Category = "Stark World Engine|Editor")
	static bool IsPlayingInEditor();

	/** The Stark World Engine subsystem of the running Play-In-Editor game (null when not playing). */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine|Editor")
	static class UStarkGameSubsystem* GetPlaySubsystem();
};
