// Stark World Engine Runtime - game-instance subsystem: the game's brain across levels (quests, dialogue, inventory, saves,
// level travel). Lives as long as the game instance, so state survives OpenLevel between Stark World Engine levels.
// UGameInstanceSubsystem: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Subsystems/UGameInstanceSubsystem
// Programming subsystems: https://dev.epicgames.com/documentation/en-us/unreal-engine/programming-subsystems-in-unreal-engine
#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "StarkTypes.h"
#include "StarkGameSubsystem.generated.h"

class UStarkRules;
class UStarkGameData;
class UStarkNpcComponent;
class AStarkEnemyCharacter;
class AStarkInteractable;
class AStarkPlayerCharacter;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FStarkToastSignature, const FString&, Message, const FString&, Kind);
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FStarkChangedSignature);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FStarkLevelSignature, int32, LevelIndex);

UCLASS()
class STARKRUNTIME_API UStarkGameSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()
public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") TObjectPtr<UStarkRules> Rules;
	UPROPERTY(BlueprintAssignable, Category = "Stark World Engine") FStarkToastSignature OnToast;
	UPROPERTY(BlueprintAssignable, Category = "Stark World Engine") FStarkChangedSignature OnChanged;
	UPROPERTY(BlueprintAssignable, Category = "Stark World Engine") FStarkLevelSignature OnLevelStarted;
	UPROPERTY(BlueprintAssignable, Category = "Stark World Engine") FStarkChangedSignature OnGameWon;

	/** Loads /Game/Stark/Data/DA_StarkGame, or Content/Stark/Data/stark_game_ue.json when the assets are missing. */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool LoadGameData();
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void NewGame();
	/** Called by AStarkGameMode::BeginPlay for every map. */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void LevelReady(UWorld* World);
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void TravelToLevel(int32 Index);
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") int32 GetLevelIndex() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") int32 GetLevelCount() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") FStarkLevelDef GetLevelDef(int32 Index) const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") bool IsSideView() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") float TerrainHeightAt(float PlanX, float PlanZ) const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") float WaterDepthAt(float PlanX, float PlanZ) const;

	// ---- saves
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool SaveToSlot(const FString& Slot, bool bQuiet = false);
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool LoadFromSlot(const FString& Slot);
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") FString SlotInfo(const FString& Slot) const;
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void DeleteSlot(const FString& Slot);

	// ---- dialogue
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Talk(const FString& NpcId, const FString& DialogId, const FString& Name, const FString& FallbackLine);
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Choose(int32 Index);
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void CloseDialogue();
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") bool IsDialogueOpen() const;

	// ---- inventory / quests (Blueprint helpers)
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void GiveItem(const FString& Id, int32 N = 1, bool bQuiet = false);
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool TakeItem(const FString& Id, int32 N = 1);
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") bool HasItem(const FString& Id, int32 N = 1) const;
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void UseItem(const FString& Id);
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Quaff();
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void StartQuest(const FString& Id);
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") FString QuestState(const FString& Id) const;
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void QuestEvent(const FString& Type, const FStarkEvent& Data);
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") FStarkStats GetStats() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") TArray<FString> TrackerLines() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") bool IsWon() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") bool IsBusy() const;

	// ---- world helpers used by the Stark World Engine actors
	void SetCheckpoint(const FVector2D& PlanXZ);
	void OnPlayerHit(float Damage);
	void SetModal(const FString& Name) { Modal = Name; BusyTime = 0.15f; Changed(); }
	FString GetModal() const { return Modal; }
	FString GoneKey(int32 ObjectIndex) const;
	bool IsGone(const FString& Key) const;
	void MarkGone(const FString& Key);
	void Changed();
	void FlushToasts();
	void PlaySfx(const FString& Name);
	/** Called every frame by AStarkGameMode::Tick. */
	void Tick(float DeltaSeconds);

	void RegisterNpc(UStarkNpcComponent* Npc);
	void UnregisterNpc(UStarkNpcComponent* Npc);
	void RegisterEnemy(AStarkEnemyCharacter* Enemy);
	void UnregisterEnemy(AStarkEnemyCharacter* Enemy);
	void RegisterInteractable(AStarkInteractable* Thing);
	void UnregisterInteractable(AStarkInteractable* Thing);
	TArray<UStarkNpcComponent*> Npcs() const;
	TArray<AStarkEnemyCharacter*> Enemies() const;
	TArray<AStarkInteractable*> Interactables() const;
	AStarkPlayerCharacter* GetPlayer() const;

	/** Where the hero appears after a load (plan x, z). */
	bool bHasPendingPos = false;
	FVector2D PendingPos = FVector2D::ZeroVector;
	bool bPorting = false;
	float BusyTime = 0.f;
	/** Automated tests only: the hero takes no damage. */
	UPROPERTY(BlueprintReadWrite, Category = "Stark World Engine") bool bTestInvulnerable = false;

private:
	FString SlotName(const FString& Slot) const;
	void EnsureFoes(const FString& Kind, int32 Need);
	UPROPERTY() TObjectPtr<UStarkGameData> GameData;
	TArray<TWeakObjectPtr<UStarkNpcComponent>> NpcList;
	TArray<TWeakObjectPtr<AStarkEnemyCharacter>> EnemyList;
	TArray<TWeakObjectPtr<AStarkInteractable>> InteractableList;
	FString Modal;
	bool bLoaded = false;
	bool bBooted = false;
};
