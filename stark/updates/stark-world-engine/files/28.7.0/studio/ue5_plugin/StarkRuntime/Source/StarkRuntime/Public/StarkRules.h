// Stark World Engine Runtime - the game rules (inventory, stats, XP, quests, dialogue, win). A plain UObject so it can be tested
// without a world (see Private/Tests/StarkRulesTest.cpp). Mirrors the Stark World Engine browser engine exactly.
// UObject: https://dev.epicgames.com/documentation/en-us/unreal-engine/objects-in-unreal-engine
#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "StarkTypes.h"
#include "StarkRules.generated.h"

UCLASS(BlueprintType)
class STARKRUNTIME_API UStarkRules : public UObject
{
	GENERATED_BODY()
public:
	void Setup(const FStarkGameDef& InDef);
	void NewGame();

	// ---- data
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") FStarkGameDef Def;
	const FStarkQuestDef* FindQuest(const FString& Id) const;
	const FStarkDialogueDef* FindDialogue(const FString& Id) const;
	const FStarkEnemyDef* FindEnemy(const FString& Kind) const;
	const FStarkLevelDef* FindLevel(int32 Index) const;
	FStarkItemDef GetItem(const FString& Id) const;
	FString NpcName(const FString& Id) const;
	FString EnemyName(const FString& Id) const;
	/** Child-safety: a child or teen (by id or age) can never be damaged, targeted, captured or romanced. */
	bool IsMinor(const FString& Id, const FString& Age = FString()) const;
	float HpMul() const;
	float DmgMul() const;
	/** Browser terrain height (plan metres) of a level at plan (x, z). */
	float TerrainHeight(int32 LevelIdx, float X, float Z) const;
	float WaterDepth(int32 LevelIdx, float X, float Z) const;

	// ---- player state (all saved)
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") float Hp = 6.f;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") int32 Lvl = 1;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") int32 Xp = 0;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") int32 Gold = 0;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") int32 Score = 0;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") TMap<FString, int32> Inventory;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") TMap<FString, FString> Equipped;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") TMap<FString, FStarkQuestProgress> Quests;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") TSet<FString> Gone;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") TSet<FString> Flags;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") int32 LevelIndex = 0;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") bool bWon = false;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") FString Difficulty = TEXT("normal");
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") int32 CheckpointLevel = -1;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") FVector2D Checkpoint = FVector2D::ZeroVector;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") TMap<FString, float> Cooldowns;
	bool bInvulnerable = false;

	// ---- inventory + stats
	int32 Count(const FString& Id) const;
	bool Has(const FString& Id, int32 N = 1) const;
	void Give(const FString& Id, int32 N = 1, bool bQuiet = false);
	bool Take(const FString& Id, int32 N = 1);
	void UseItem(const FString& Id);
	void Quaff();
	FStarkStats Stats() const;
	int32 XpNeed() const;
	void AddXp(int32 N);
	/** -> true when the hit was fatal (gold is reduced; the caller respawns the hero). */
	bool Hurt(float Damage);
	bool HasAbility(const FString& Name) const;
	bool UseAbility(const FString& Name);
	void TickCooldowns(float DeltaSeconds);

	// ---- quests
	FString QuestState(const FString& Id) const;
	void StartQuest(const FString& Id, bool bQuiet = false);
	const FStarkQuestStep* CurrentStep(const FStarkQuestDef& Q) const;
	void CompleteQuest(const FStarkQuestDef& Q);
	void Event(const FString& Type, const FStarkEvent& Data);
	FString StepText(const FStarkQuestStep& S) const;
	TArray<const FStarkQuestDef*> ActiveQuests() const;
	const FStarkQuestStep* EscortStep(const FString& NpcId) const;
	bool IsTalkTarget(const FString& NpcId) const;
	bool OffersQuest(const FString& NpcId) const;
	void CheckWin();
	/** Auto quests of a level (called when the level starts). */
	void StartLevelQuests(int32 LevelIdx);

	// ---- dialogue
	bool Cond(const FStarkCondition& C) const;
	void Act(const FStarkAction& A);
	void Talk(const FString& NpcId, const FString& DialogId, const FString& Name, const FString& FallbackLine);
	void ShowNode(const FString& NodeId);
	void Choose(int32 Index);
	void CloseDialogue();
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") bool bDialogueOpen = false;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") FString Speaker;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") FString Line;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") TArray<FStarkChoice> VisibleChoices;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") FString DialogueNpcName;
	FStarkDialogueDef ActiveDialogue;
	FString NodeId;

	// ---- messages for the HUD (the subsystem broadcasts and clears them)
	TArray<TPair<FString, FString>> PendingToasts;
	void Toast(const FString& Message, const FString& Kind = FString());
	/** Asks the world to keep "defeat N" steps possible (respawn foes). Set by the subsystem. */
	TFunction<void(const FString& /*Kind*/, int32 /*Need*/)> EnsureFoes;
	/** Called when the game is won. */
	TFunction<void()> OnWin;

private:
	void InitStep(const FStarkQuestDef& Q);
	void Foes(const FStarkQuestDef& Q);
	bool StepDone(const FStarkQuestDef& Q) const;
	void CheckStep(const FStarkQuestDef& Q);
};
