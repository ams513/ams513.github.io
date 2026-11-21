// Stark World Engine Runtime - enemies. AStarkEnemyAIController runs the browser engine's brain natively (patrol -> chase ->
// return home, archers kite and shoot, brutes/bosses wind up a slam, bosses fire volleys and enrage; in 2.5D chapters
// they walk back and forth and can be stomped). Assign BehaviorTreeAsset to replace the native brain with a Behavior
// Tree built from Resources/BT_StarkEnemy.json (the same logic as nodes).
// AAIController: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/AIModule/AAIController
// Behavior Trees: https://dev.epicgames.com/documentation/en-us/unreal-engine/behavior-trees-in-unreal-engine
#pragma once

#include "CoreMinimal.h"
#include "AIController.h"
#include "GameFramework/Character.h"
#include "StarkTypes.h"
#include "StarkEnemy.generated.h"

class UBehaviorTree;
class UStaticMeshComponent;
class UChildActorComponent;

UCLASS()
class STARKRUNTIME_API AStarkEnemyCharacter : public ACharacter
{
	GENERATED_BODY()
public:
	AStarkEnemyCharacter();
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 ObjectIndex = -1;
	/** Overrides the "level:index" key that remembers a slain enemy (2.5D tiles use "level:tX_Y"). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString GoneKeyOverride;
	/** grunt | archer | brute | wisp | boss */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Kind = TEXT("grunt");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString EnemyId;
	/** child | teen | adult. Child-safety: a minor is never an enemy (removed at BeginPlay, never takes damage). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Age = TEXT("adult");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString DisplayName;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 HpOverride = 0;
	/** wander radius around home, metres */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Patrol = 5.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float SizeScale = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool bSideView = false;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TObjectPtr<UStaticMeshComponent> BodyMesh;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine|Art") TObjectPtr<UChildActorComponent> Visual;
	/** Fab / Megascans / your own creature Blueprint shown instead of the proxy (AI and combat stay). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine|Art") TSubclassOf<AActor> VisualClass;

	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") float Hp = 3.f;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") float MaxHp = 3.f;
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") FString State = TEXT("patrol");
	UPROPERTY(BlueprintReadOnly, Category = "Stark World Engine") bool bDead = false;
	FStarkEnemyDef Def;
	FVector Home = FVector::ZeroVector;
	FVector WanderTarget = FVector::ZeroVector;
	float WanderT = 0.f, Cooldown = 0.6f, ShotT = 1.f, WindUp = 0.f, VolleyT = 4.f, HitT = 0.f, AliveT = 0.f;
	float SideDir = 1.f;
	bool bEnraged = false;

	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void TakeHit(float Damage, FVector Direction);
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") bool IsBoss() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") bool IsProtected() const;
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") FString Title() const;
	FString GetGoneKey() const;
	void Die();
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
};

UCLASS()
class STARKRUNTIME_API AStarkEnemyAIController : public AAIController
{
	GENERATED_BODY()
public:
	AStarkEnemyAIController();
	/** Optional: run this Behavior Tree instead of the native brain (see Resources/BT_StarkEnemy.json). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine|AI") TObjectPtr<UBehaviorTree> BehaviorTreeAsset;
	virtual void Tick(float DeltaSeconds) override;
protected:
	virtual void OnPossess(APawn* InPawn) override;
private:
	void Think3D(AStarkEnemyCharacter* E, float Dt);
	void Think2D(AStarkEnemyCharacter* E, float Dt);
	void Shoot(AStarkEnemyCharacter* E, const FVector& Velocity, float Damage, const FLinearColor& Color);
	bool bUsingTree = false;
};
