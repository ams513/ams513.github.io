// Stark World Engine Runtime - editor helpers (see StarkEditorLibrary.h).
// Landscape import from code follows the editor's own "New Landscape" path (ALandscapeProxy::Import with a height map
// per edit layer guid): https://dev.epicgames.com/documentation/en-us/unreal-engine/landscape-technical-guide-in-unreal-engine
// GEditor / PlayWorld: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Editor/UnrealEd/UEditorEngine
#include "StarkEditorLibrary.h"
#include "StarkGameSubsystem.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "Landscape.h"
#include "LandscapeInfo.h"
#include "LandscapeProxy.h"
#include "Materials/MaterialInterface.h"
#if WITH_EDITOR
#include "Editor.h"
#endif

ALandscape* UStarkEditorLibrary::CreateLandscapeFromHeights(const TArray<int32>& Heights, int32 SizeX, int32 SizeY,
	FVector Location, FVector Scale, UMaterialInterface* Material, int32 QuadsPerSection, int32 SectionsPerComponent)
{
#if WITH_EDITOR
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	const int32 ComponentQuads = QuadsPerSection * SectionsPerComponent;
	if (!World || SizeX < 2 || SizeY < 2 || Heights.Num() != SizeX * SizeY || ComponentQuads <= 0
		|| (SizeX - 1) % ComponentQuads != 0 || (SizeY - 1) % ComponentQuads != 0)
	{
		UE_LOG(LogTemp, Warning, TEXT("[Stark World Engine] CreateLandscapeFromHeights: bad size %dx%d (%d heights)"), SizeX, SizeY, Heights.Num());
		return nullptr;
	}
	TArray<uint16> Data;
	Data.SetNumUninitialized(Heights.Num());
	for (int32 i = 0; i < Heights.Num(); ++i) { Data[i] = (uint16)FMath::Clamp(Heights[i], 0, 65535); }
	FActorSpawnParameters Params;
	ALandscape* Landscape = World->SpawnActor<ALandscape>(Location, FRotator::ZeroRotator, Params);
	if (!Landscape) { return nullptr; }
	Landscape->SetActorScale3D(Scale);
	TMap<FGuid, TArray<uint16>> HeightData;
	HeightData.Add(FGuid(), MoveTemp(Data));
	TMap<FGuid, TArray<FLandscapeImportLayerInfo>> LayerInfos;
	LayerInfos.Add(FGuid(), TArray<FLandscapeImportLayerInfo>());
	Landscape->Import(FGuid::NewGuid(), 0, 0, SizeX - 1, SizeY - 1, SectionsPerComponent, QuadsPerSection, HeightData,
		nullptr, LayerInfos, ELandscapeImportAlphamapType::Additive);
	if (ULandscapeInfo* Info = Landscape->GetLandscapeInfo()) { Info->UpdateLayerInfoMap(Landscape); }
	Landscape->RegisterAllComponents();
	if (Material) { Landscape->EditorSetLandscapeMaterial(Material); }
	Landscape->PostEditChange();
	return Landscape;
#else
	return nullptr;
#endif
}

bool UStarkEditorLibrary::StartPlayInEditor()
{
#if WITH_EDITOR
	if (!GEditor || GEditor->PlayWorld) { return false; }
	FRequestPlaySessionParams Params;
	GEditor->RequestPlaySession(Params);
	return true;
#else
	return false;
#endif
}

bool UStarkEditorLibrary::StopPlayInEditor()
{
#if WITH_EDITOR
	if (!GEditor || !GEditor->PlayWorld) { return false; }
	GEditor->RequestEndPlayMap();
	return true;
#else
	return false;
#endif
}

bool UStarkEditorLibrary::IsPlayingInEditor()
{
#if WITH_EDITOR
	return GEditor && GEditor->PlayWorld != nullptr;
#else
	return false;
#endif
}

UStarkGameSubsystem* UStarkEditorLibrary::GetPlaySubsystem()
{
#if WITH_EDITOR
	UWorld* World = GEditor ? GEditor->PlayWorld.Get() : nullptr;
	UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
	return GI ? GI->GetSubsystem<UStarkGameSubsystem>() : nullptr;
#else
	return nullptr;
#endif
}
