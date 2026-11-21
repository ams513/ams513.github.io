// Stark World Engine Runtime - save slot contents (slots 1-3 + autosave), same fields as the browser engine's snapshot.
// USaveGame: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/USaveGame
// Saving and loading: https://dev.epicgames.com/documentation/en-us/unreal-engine/saving-and-loading-your-game-in-unreal-engine
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/SaveGame.h"
#include "StarkTypes.h"
#include "StarkSaveGame.generated.h"

UCLASS()
class STARKRUNTIME_API UStarkSaveGame : public USaveGame
{
	GENERATED_BODY()
public:
	UPROPERTY(SaveGame) int32 Version = 2;
	UPROPERTY(SaveGame) FString SaveKey;
	UPROPERTY(SaveGame) int32 LevelIndex = 0;
	UPROPERTY(SaveGame) bool bHasPos = false;
	UPROPERTY(SaveGame) FVector2D PosXZ = FVector2D::ZeroVector;
	UPROPERTY(SaveGame) float Hp = 6.f;
	UPROPERTY(SaveGame) int32 Lvl = 1;
	UPROPERTY(SaveGame) int32 Xp = 0;
	UPROPERTY(SaveGame) int32 Gold = 0;
	UPROPERTY(SaveGame) int32 Score = 0;
	UPROPERTY(SaveGame) TMap<FString, int32> Inventory;
	UPROPERTY(SaveGame) TMap<FString, FString> Equipped;
	UPROPERTY(SaveGame) TMap<FString, FStarkQuestProgress> Quests;
	UPROPERTY(SaveGame) TArray<FString> Gone;
	UPROPERTY(SaveGame) TArray<FString> Flags;
	UPROPERTY(SaveGame) int32 CheckpointLevel = -1;
	UPROPERTY(SaveGame) FVector2D Checkpoint = FVector2D::ZeroVector;
	UPROPERTY(SaveGame) bool bWon = false;
	UPROPERTY(SaveGame) FString Difficulty;
	UPROPERTY(SaveGame) FDateTime SavedAt;
};
